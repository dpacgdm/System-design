# Topic 5: DNS Resolution

## Learning Objectives

```
╔══════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                     ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. Trace a DNS query from browser to authoritative         ║
║      nameserver and back, identifying every cache            ║
║      layer and failure point along the way                   ║
║                                                              ║
║   2. Explain how DNS is used as a load balancing and         ║
║      traffic routing tool in production systems              ║
║      (GeoDNS, weighted routing, failover)                    ║
║                                                              ║
║   3. Diagnose DNS-related production incidents using         ║
║      dig, nslookup, and packet captures                      ║
║                                                              ║
║   4. Identify and fix common DNS failure patterns:           ║
║      TTL misconfiguration, propagation delays,               ║
║      cache poisoning, NXDOMAIN storms, and the               ║
║      specific failure mode that took down Facebook           ║
║      for 6 hours in 2021                                     ║
║                                                              ║
║   5. Design DNS architecture for a globally                  ║
║      distributed system with failover capabilities           ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "DNS is just a phonebook lookup"                     ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. DNS is a hierarchical, cached, eventually-consistent           ║
║   distributed system with TTL-based propagation, anycast routing,       ║
║   and traffic-steering policies. It is load balancing, failover,        ║
║   and geo-routing — not a simple name→IP map.                           ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Set TTL to 60s for fast failover"                   ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Low TTL increases resolver load and does not guarantee         ║
║   instant propagation — resolvers cache past TTL (minimum TTL           ║
║   clamping), and client OS caches ignore TTL changes until              ║
║   expiry. Failover requires health checks + weighted routing,           ║
║   not TTL alone.                                                        ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "DNS changes propagate instantly worldwide"          ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Each resolver caches independently. A record change at         ║
║   the authoritative server can take TTL × cache depth to reach          ║
║   all clients. During cutover, old and new IPs serve traffic            ║
║   simultaneously — plan for overlap.                                    ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "DNS round-robin is as good as an L7 LB"             ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. DNS returns multiple A records but clients cache ONE           ║
║   answer and retry the same IP. No health checking, no weighted         ║
║   distribution, no connection draining. DNS steers traffic; it          ║
║   does not manage connections.                                          ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Private/internal DNS doesn't need redundancy"       ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Facebook's 2021 outage started with BGP withdrawal of          ║
║   authoritative nameserver routes. Internal DNS failure cascades        ║
║   to service discovery, database connections, and mesh routing.         ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "CNAME chains and wildcards are harmless"            ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. CNAME at zone apex is invalid (use ALIAS/ANAME). Deep          ║
║   CNAME chains add latency per hop. Wildcard records interact           ║
║   badly with ACME cert validation and can mask misconfigured            ║
║   subdomains until an incident exposes them.                            ║
╚═════════════════════════════════════════════════════════════════════════╝
```

---

## Why DNS Matters More Than You Think

```
Every single network request starts with DNS.

When you type "google.com" in your browser:
  BEFORE any TCP handshake...
  BEFORE any TLS negotiation...
  BEFORE any HTTP request...

  Your machine must answer ONE question:
  "What IP address is google.com?"

  If DNS breaks, NOTHING works.
  Not your website. Not your API. Not your database
  connections. Not your microservice mesh. Nothing.

  DNS is the single most critical piece of internet
  infrastructure, and most engineers barely understand it.

REAL OUTAGES CAUSED BY DNS:
  → Facebook, Oct 2021: 6 hours, ALL services down
    (BGP withdrawal removed DNS nameserver routes)
  → Cloudflare, Jul 2020: 27 minutes, widespread outage
    (bad router rule dropped DNS traffic)
  → Dyn DDoS, Oct 2016: Twitter, Reddit, Netflix,
    GitHub all down for hours
    (DDoS attack on DNS provider Dyn)
  → Microsoft Azure, Apr 2021: DNS configuration error
    caused global outage
```

---

## The DNS Hierarchy

DNS is a **distributed, hierarchical database**. Understanding the hierarchy is essential.

```
THE DNS TREE:

                        . (ROOT)
                        │
           ╭────────────┼────────────╮
           │            │            │
         .com         .org         .net        (TLDs)
           │            │            │
     ╭─────┼─────╮     │      ╭─────┼─────╮
     │     │     │     │      │     │     │
  google amazon example  wikipedia  cloudflare netflix
     │     │     │                  │
   www   aws   www                cdn
   mail  s3    api                api
   dns   ec2   blog

EVERY domain is read RIGHT TO LEFT:

  www.example.com.
   │      │     │ │
   │      │     │ ╰── Root (the trailing dot, usually hidden)
   │      │     ╰──── TLD (Top-Level Domain)
   │      ╰────────── Second-Level Domain (SLD)
   ╰───────────────── Subdomain

The trailing dot matters!
  "example.com." = absolute/fully qualified domain name (FQDN)
  "example.com"  = could be relative (depends on search domain)

  In DNS queries, the dot is always there.
  Your browser just hides it from you.
```

## DNS Record Types (You Must Know All of These)

```
A RECORD (Address):
  Maps domain → IPv4 address
  example.com.  A  93.184.216.34

  The most fundamental record type.
  "What IPv4 address is this domain?"

AAAA RECORD (IPv6 Address):
  Maps domain → IPv6 address
  example.com.  AAAA  2606:2800:220:1:248:1893:25c8:1946

  Same as A record but for IPv6.
  "Quad-A" because IPv6 is 4× the size of IPv4.

CNAME RECORD (Canonical Name):
  Maps domain → another domain (alias)
  www.example.com.  CNAME  example.com.
  blog.example.com. CNAME  medium.com.

  "This domain is actually an alias for THAT domain.
   Go look up THAT domain instead."

  CRITICAL RULES:
  → CNAME cannot coexist with other records for same name
  → CNAME at zone apex (example.com) is FORBIDDEN by RFC
    → This is why you can't CNAME your root domain
    → Workaround: ALIAS/ANAME records (non-standard,
      supported by Route 53, Cloudflare, etc.)
  → CNAME creates an extra DNS lookup (performance hit)

NS RECORD (Name Server):
  Declares which servers are authoritative for this domain
  example.com.  NS  ns1.example.com.
  example.com.  NS  ns2.example.com.

  "If you want to know about example.com,
   ask ns1.example.com or ns2.example.com."

  This is the DELEGATION mechanism.
  The root servers delegate to TLD servers.
  TLD servers delegate to your domain's nameservers.

MX RECORD (Mail Exchange):
  Where to deliver email for this domain
  example.com.  MX  10  mail1.example.com.
  example.com.  MX  20  mail2.example.com.

  The number (10, 20) is PRIORITY — lower = preferred.
  mail1 is tried first. If it fails, try mail2.

TXT RECORD (Text):
  Arbitrary text data associated with a domain
  example.com.  TXT  "v=spf1 include:_spf.google.com ~all"

  Used for:
  → SPF (email authentication — who can send as you)
  → DKIM (email signing verification)
  → DMARC (email policy)
  → Domain ownership verification
    (Google: "Add this TXT record to prove you own it")
  → Let's Encrypt ACME challenges (TLS cert issuance)

SRV RECORD (Service):
  Specifies host and port for specific services
  _sip._tcp.example.com.  SRV  10 60 5060 sip.example.com.

  Format: priority weight port target

  Used by: VoIP, XMPP, Minecraft, some microservice
  discovery systems

PTR RECORD (Pointer — Reverse DNS):
  Maps IP address → domain (reverse of A record)
  34.216.184.93.in-addr.arpa.  PTR  example.com.

  Used for:
  → Reverse DNS lookups ("What domain owns this IP?")
  → Email spam prevention (mail servers check PTR)
  → Security auditing and logging

SOA RECORD (Start of Authority):
  Metadata about the DNS zone
  example.com.  SOA  ns1.example.com. admin.example.com. (
    2024011501  ; Serial number (version)
    3600        ; Refresh interval (secondary checks primary)
    900         ; Retry interval (if refresh fails)
    1209600     ; Expire (secondary stops serving if no refresh)
    86400       ; Minimum TTL (negative caching)
  )
```

---

## The Full DNS Resolution Process

This is the complete journey of a DNS query. Every cache layer, every server, every decision point.

```
USER TYPES: www.example.com

STEP 1: BROWSER DNS CACHE
━━━━━━━━━━━━━━━━━━━━━━━━━

  Browser checks its own internal DNS cache.

  Chrome: chrome://net-internals/#dns
  Firefox: about:networking#dns

  Cache duration: Respects TTL from DNS response.
  Typically 60-300 seconds.

  If found → DONE. Use cached IP. No network request.
  If not found → proceed to Step 2.


STEP 2: OS DNS CACHE (Stub Resolver)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Browser calls the operating system's resolver.

  Linux:   systemd-resolved (modern) or nscd
  macOS:   mDNSResponder
  Windows: DNS Client service

  The OS checks:
  a) /etc/hosts file (hardcoded mappings)
     127.0.0.1  localhost
     93.184.216.34  www.example.com  ← If here, done!

  b) OS DNS cache
     Similar to browser cache. Separate layer.

  c) /etc/resolv.conf — which DNS resolver to ask
     nameserver 8.8.8.8        ← Google's resolver
     nameserver 1.1.1.1        ← Cloudflare's resolver
     search corp.example.com   ← Search domain suffix

  If found in cache → DONE.
  If not found → proceed to Step 3.


STEP 3: RECURSIVE RESOLVER (The Workhorse)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  The OS sends the query to the configured recursive
  resolver. This is usually:

  → Your ISP's DNS resolver
  → Google Public DNS (8.8.8.8)
  → Cloudflare DNS (1.1.1.1)
  → Your company's internal DNS resolver
  → In Kubernetes: CoreDNS / kube-dns

  The recursive resolver does ALL the hard work.
  It's called "recursive" because it recursively
  follows the DNS hierarchy on your behalf.

  First, it checks its OWN cache.
  If found → return cached answer to your OS.
  If not found → start the recursive resolution:


STEP 4: ROOT NAME SERVERS
━━━━━━━━━━━━━━━━━━━━━━━━━

  Recursive resolver asks a root nameserver:
  "Where can I find www.example.com?"

  There are 13 root server clusters (a.root-servers.net
  through m.root-servers.net), operated by 12 different
  organizations worldwide.

  "13 clusters" is misleading — there are actually
  1,500+ physical servers using ANYCAST routing.
  When you query a.root-servers.net, you hit the
  NEAREST physical instance.

  The root server doesn't know the answer.
  But it knows who manages .com:

  Root server responds:
  "I don't know www.example.com, but .com is handled
   by these nameservers:"

  REFERRAL:
    com.  NS  a.gtld-servers.net.
    com.  NS  b.gtld-servers.net.
    com.  NS  c.gtld-servers.net.
    ... (13 TLD servers for .com)

    + GLUE RECORDS (IP addresses of TLD servers):
    a.gtld-servers.net.  A  192.5.6.30
    b.gtld-servers.net.  A  192.33.14.30

  Why glue records?
    Without them, you'd need to resolve
    "a.gtld-servers.net" to get its IP...
    but to resolve that, you'd need to query the
    .net TLD server... which you'd need to resolve...
    → INFINITE LOOP.
    Glue records break the loop by providing IPs
    directly in the referral.


STEP 5: TLD NAME SERVERS
━━━━━━━━━━━━━━━━━━━━━━━━

  Recursive resolver asks a .com TLD server:
  "Where can I find www.example.com?"

  The TLD server manages ALL .com domains.
  It doesn't know the IP of www.example.com.
  But it knows which nameservers are AUTHORITATIVE
  for example.com:

  TLD server responds:
  "I don't know www.example.com, but example.com
   is handled by these nameservers:"

  REFERRAL:
    example.com.  NS  ns1.example.com.
    example.com.  NS  ns2.example.com.

    GLUE:
    ns1.example.com.  A  93.184.216.1
    ns2.example.com.  A  93.184.216.2

  These are the AUTHORITATIVE nameservers for
  example.com. They are the source of truth.


STEP 6: AUTHORITATIVE NAME SERVERS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Recursive resolver asks ns1.example.com:
  "What is the IP address of www.example.com?"

  The authoritative server has the actual DNS records.
  It looks up its zone file and responds:

  ANSWER:
    www.example.com.  A  93.184.216.34
    TTL: 300 (cache this for 300 seconds)

  This is the AUTHORITATIVE ANSWER.
  The buck stops here.


STEP 7: RESPONSE PROPAGATION (unwinding the recursion)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Authoritative NS → Recursive resolver
    Resolver caches the answer (TTL: 300s)

  Recursive resolver → OS stub resolver
    OS caches the answer (TTL: 300s)

  OS → Browser
    Browser caches the answer (TTL: 300s)

  Browser: "93.184.216.34! Now I can start the
           TCP handshake."


THE COMPLETE DIAGRAM:

  Browser     OS        Recursive     Root      TLD     Authoritative
  Cache      Cache      Resolver     Servers   Servers   Nameserver
    │          │            │           │         │          │
    ├─miss─►   │            │           │         │          │
    │   ├─miss─►            │           │         │          │
    │   │       ├─miss──────►           │         │          │
    │   │       │    ◄──referral (.com) │         │          │
    │   │       │           │           │         │          │
    │   │       ├───────────────────────►         │          │
    │   │       │    ◄──referral (ns1.example.com)│          │
    │   │       │           │           │         │          │
    │   │       ├─────────────────────────────────►          │
    │   │       │    ◄──ANSWER: 93.184.216.34─────│          │
    │   │       │           │           │         │          │
    │   │  ◄────┤ (cache)   │           │         │          │
    │◄──┤(cache)│           │           │         │          │
    │   │       │           │           │         │          │

  Total queries for one UNCACHED lookup: 3-4
  Total time: 20-120ms (depending on geography)
  Subsequent lookups (cached): 0ms-1ms
```

---

## TTL: Time To Live (Critical for SRE)

```
Every DNS record has a TTL value — how long resolvers
are ALLOWED to cache the answer.

example.com.  300  IN  A  93.184.216.34
               │
               ╰── TTL: 300 seconds (5 minutes)

WHAT TTL MEANS IN PRACTICE:

  TTL = 300:
    After resolving example.com, the recursive resolver
    caches it for 300 seconds. During that time, it will
    NOT query the authoritative server again — it returns
    the cached answer.

    If you change the IP at the authoritative server:
    → Some resolvers have the OLD IP (cached)
    → Some resolvers get the NEW IP (cache expired)
    → For up to 300 seconds, different users see
      different IPs!
    → This is "DNS propagation"

TTL TRADE-OFFS:

  SHORT TTL (e.g., 30-60 seconds):
    ✓ Fast failover — change IP, users follow quickly
    ✓ DNS-based load balancing responds quickly
    ✗ MORE DNS queries → more load on authoritative servers
    ✗ MORE DNS queries → more latency for users
    ✗ Higher cost if using pay-per-query DNS (Route 53)
    Used by: Services that need fast failover,
             blue-green deployments

  LONG TTL (e.g., 3600-86400 seconds):
    ✓ Fewer DNS queries → less load, less cost
    ✓ Faster for users (always cached)
    ✗ SLOW failover — if IP changes, users stuck
      with old IP for up to TTL duration
    ✗ DNS changes take hours to propagate
    Used by: Stable services that rarely change IPs,
             CDN-fronted services

  PRODUCTION PRACTICE:
    Before a migration or IP change:
    1. Lower TTL to 60s (weeks in advance!)
    2. Wait for old TTL to expire everywhere
    3. Make the change
    4. Wait for new records to propagate (~60s)
    5. Raise TTL back to normal

    If you skip step 1 and your TTL was 86400 (24 hours):
    → After changing IP, some users are stuck on old IP
      for up to 24 HOURS
    → This has caused MANY production incidents

IMPORTANT: TTL IS A REQUEST, NOT A GUARANTEE

  Resolvers are SUPPOSED to respect TTL. But:
  → Some ISP resolvers ignore TTL and cache for hours
  → Some corporate resolvers cache longer "for performance"
  → Some resolvers enforce a MINIMUM TTL (e.g., 300s)
    even if you set TTL = 10
  → Java's default DNS cache is INFINITE for positive
    lookups (yes, really — networkaddress.cache.ttl)
    → FIX: Set -Dsun.net.inetaddr.ttl=60 in JVM args
    → This has caused MANY Java production outages
  → Some CDNs cache DNS independently

  You can set TTL = 30, but you cannot guarantee
  ALL resolvers will refresh in 30 seconds.
```

## Negative Caching

```
What happens when a domain DOESN'T exist?

  Query: doesnotexist.example.com
  Response: NXDOMAIN (Non-Existent Domain)

  This NXDOMAIN response is ALSO cached!
  Duration: SOA record's minimum TTL field

  Why this matters:
  → You create a new subdomain (api.example.com)
  → A client queried it BEFORE you created it
  → Client received NXDOMAIN, cached it
  → You create the record
  → Client STILL gets NXDOMAIN from its cache!
  → Must wait for negative cache TTL to expire

  SRE impact: When launching new services, some users
  may get NXDOMAIN for minutes after you've created
  the DNS record.
```

---

## DNS as a Load Balancing & Traffic Management Tool

DNS isn't just for name resolution. It's a powerful traffic routing tool.

### Round-Robin DNS

```
The simplest form of DNS-based load balancing:

  example.com.  A  93.184.216.34
  example.com.  A  93.184.216.35
  example.com.  A  93.184.216.36

  Multiple A records for the same domain.
  Resolvers return them in rotating order:

  Query 1: [.34, .35, .36]
  Query 2: [.35, .36, .34]
  Query 3: [.36, .34, .35]

  Clients typically connect to the FIRST IP.
  → Rough 33/33/33 traffic distribution.

PROBLEMS:
  → No health checking — if .35 is dead, 1/3 of
    users still get sent there
  → Caching: resolver caches all 3 IPs, client
    uses the same one until TTL expires
  → Uneven distribution with caching
  → No awareness of server load
  → No geographic awareness

  Round-robin DNS is NOT real load balancing.
  It's better than nothing, but production systems
  need more.
```

### AWS Route 53 (and similar managed DNS services)

```
Route 53 offers sophisticated DNS-based traffic management:

1. WEIGHTED ROUTING:
   Distribute traffic by percentage:

   example.com  A  1.1.1.1  weight=70   (70% of traffic)
   example.com  A  2.2.2.2  weight=20   (20% of traffic)
   example.com  A  3.3.3.3  weight=10   (10% of traffic)

   Use case: Canary deployments
   → Send 5% of traffic to new version
   → Monitor errors
   → Gradually increase weight
   → Much simpler than application-level canary

2. LATENCY-BASED ROUTING:
   Route to the region with lowest latency:

   example.com → query from Tokyo  → respond with Asia IP
   example.com → query from London → respond with EU IP
   example.com → query from NYC    → respond with US-East IP

   Route 53 maintains a latency database between
   resolvers and AWS regions. Automatically routes
   to the fastest region for each user.

3. GEOLOCATION ROUTING:
   Route based on user's geographic location:

   example.com from Europe → EU servers
   example.com from Asia   → Asia servers
   example.com from USA    → US servers
   example.com default     → US servers (fallback)

   Use cases:
   → Content localization (show local language)
   → Legal compliance (GDPR, data residency)
   → Performance optimization

4. FAILOVER ROUTING:
   Active-passive failover:

   example.com  PRIMARY   → 1.1.1.1 (health check: /health)
   example.com  SECONDARY → 2.2.2.2 (only if primary fails)

   Route 53 actively health-checks the primary endpoint.
   If health check fails → automatically returns secondary IP.

   Health check options:
   → HTTP/HTTPS (check specific URL)
   → TCP (check port is open)
   → CloudWatch alarm integration
   → Can check multiple endpoints in a chain

5. MULTIVALUE ANSWER:
   Return up to 8 healthy IPs:

   Like round-robin, but with HEALTH CHECKS.
   Unhealthy IPs are automatically removed from answers.

   This is "poor man's load balancing" — better than
   round-robin DNS because dead servers are excluded.
```

### GeoDNS — How Global Traffic Routing Works

```
FULL ARCHITECTURE OF A GLOBAL SERVICE:

User in Tokyo queries: api.example.com

Step 1: Query reaches Route 53 (or Cloudflare DNS)
Step 2: Route 53 determines user is in Asia-Pacific
        (based on resolver IP / EDNS client subnet)
Step 3: Route 53 returns IP of Asia-Pacific load balancer

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   User (Tokyo)                                               ║
  ║     │                                                        ║
  ║     ▼                                                        ║
  ║   Route 53 GeoDNS                                            ║
  ║     │                                                        ║
  ║     ├── User in Americas → us-east-alb.example.com           ║
  ║     │                       (Virginia)                       ║
  ║     ├── User in Europe   → eu-west-alb.example.com           ║
  ║     │                       (Ireland)                        ║
  ║     ├── User in Asia     → ap-ne-alb.example.com             ║
  ║     │                       (Tokyo) ◄── THIS ONE             ║
  ║     ╰── Default          → us-east-alb.example.com           ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝

EDNS CLIENT SUBNET (ECS):

  Problem: GeoDNS routes based on the RESOLVER's location,
           not the USER's location.

  User in Tokyo → uses Google DNS (8.8.8.8)
  Google DNS resolver handling this query might be in
  California.
  → Route 53 sees California resolver → routes to US!
  → User in Tokyo gets sent to US server → high latency!

  Fix: EDNS Client Subnet extension
  → Resolver includes part of user's IP in the query:
    "Resolve api.example.com, client subnet: 203.0.113.0/24"
  → Route 53 sees Japanese IP prefix → routes to Tokyo
  → Correct routing even through geographically distant resolvers

  Google DNS, Cloudflare DNS, and most modern resolvers
  support ECS. But some don't — so geographic routing
  is never 100% accurate.
```

---

## DNS in Kubernetes (Critical for Microservices)

```
In Kubernetes, DNS is how services find each other.
CoreDNS is the default DNS server in Kubernetes.

SERVICE DISCOVERY VIA DNS:

  When you create a Kubernetes Service:

  apiVersion: v1
  kind: Service
  metadata:
    name: user-service
    namespace: production
  spec:
    selector:
      app: user-service
    ports:
      - port: 80

  Kubernetes automatically creates DNS records:

  user-service.production.svc.cluster.local
  │              │          │      │
  │              │          │      ╰── Cluster domain
  │              │          ╰── "svc" = service
  │              ╰── Namespace
  ╰── Service name

  From any pod in the cluster:
    curl http://user-service.production.svc.cluster.local

  Or shorter (if in the same namespace):
    curl http://user-service

HOW KUBERNETES DNS WORKS:

  ╔══════════════════════════════════════════════════════════════╗
  ║   Pod                                                        ║
  ║   /etc/resolv.conf:                                          ║
  ║     nameserver 10.96.0.10  ← CoreDNS IP                      ║
  ║     search production.svc.cluster.local                      ║
  ║            svc.cluster.local                                 ║
  ║            cluster.local                                     ║
  ║     ndots: 5                                                 ║
  ╚══════════════════════════════════════════════════════════════╝
                 │
                 ▼
  ╔══════════════════════════════════════════════════════════════╗
  ║   CoreDNS (runs as pods in kube-system)                      ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   Watches Kubernetes API for Service changes                 ║
  ║   Maintains DNS records for all Services                     ║
  ║   Forwards external queries to upstream DNS                  ║
  ╚══════════════════════════════════════════════════════════════╝

NDOTS PROBLEM (CRITICAL SRE KNOWLEDGE):

  ndots: 5 means:
  "If the queried name has fewer than 5 dots,
   try appending search domains first."

  Query: api.example.com (2 dots, < 5)

  CoreDNS tries IN ORDER:
    1. api.example.com.production.svc.cluster.local → NXDOMAIN
    2. api.example.com.svc.cluster.local → NXDOMAIN
    3. api.example.com.cluster.local → NXDOMAIN
    4. api.example.com → SUCCESS!

  ONE external DNS lookup generated FOUR DNS queries!
  Three of them wasted (NXDOMAIN).

  At scale:
    1000 pods × 100 external queries/sec × 4 queries each
    = 400,000 queries/sec hitting CoreDNS
    = CoreDNS becomes a bottleneck
    = DNS latency spikes
    = ALL services slow down

  FIX:
  → Use FQDNs with trailing dot for external domains:
    "api.example.com." (trailing dot = absolute, skip search)
  → Lower ndots in pod spec:
    dnsConfig:
      options:
        - name: ndots
          value: "2"
  → Use NodeLocal DNSCache (DaemonSet that caches on each node)
  → This is one of the most common Kubernetes performance issues
```

---

## DNS Protocol Details

```
DNS primarily uses UDP port 53.

WHY UDP?
  → DNS queries and responses are usually small
    (< 512 bytes for traditional DNS)
  → UDP: one packet out, one packet back = fast
  → TCP would add a 3-way handshake → 2 extra RTTs
  → For a simple lookup, TCP triples the latency

WHEN DOES DNS USE TCP?
  → Response > 512 bytes (truncated flag set)
    → Resolver retries over TCP
  → Zone transfers (AXFR/IXFR) between DNS servers
    → Full database sync, large data, needs reliability
  → DNSSEC responses (signatures make responses larger)
  → DNS over TLS (DoT, port 853)
  → DNS over HTTPS (DoH, port 443)

DNS MESSAGE FORMAT:

  ╔══════════════════════════════════════════════════════════════╗
  ║   Header (12 bytes)                                          ║
  ║   - Transaction ID (16 bits)                                 ║
  ║   - Flags (QR, Opcode, AA,                                   ║
  ║     TC, RD, RA, RCODE)                                       ║
  ║   - Question count                                           ║
  ║   - Answer count                                             ║
  ║   - Authority count                                          ║
  ║   - Additional count                                         ║
  ╠══════════════════════════════════════════════════════════════╣
  ║   Question Section                                           ║
  ║   "What are you asking?"                                     ║
  ║   - Name: www.example.com                                    ║
  ║   - Type: A                                                  ║
  ║   - Class: IN (Internet)                                     ║
  ╠══════════════════════════════════════════════════════════════╣
  ║   Answer Section                                             ║
  ║   "Here's the answer"                                        ║
  ║   - Name: www.example.com                                    ║
  ║   - Type: A                                                  ║
  ║   - TTL: 300                                                 ║
  ║   - Data: 93.184.216.34                                      ║
  ╠══════════════════════════════════════════════════════════════╣
  ║   Authority Section                                          ║
  ║   "These servers are auth"                                   ║
  ║   - NS records                                               ║
  ╠══════════════════════════════════════════════════════════════╣
  ║   Additional Section                                         ║
  ║   "You might also need these"                                ║
  ║   - Glue records (A records                                  ║
  ║     for nameservers)                                         ║
  ╚══════════════════════════════════════════════════════════════╝

KEY FLAGS:
  QR: Query (0) or Response (1)
  AA: Authoritative Answer (server is authoritative for domain)
  TC: Truncated (response too big for UDP, retry with TCP)
  RD: Recursion Desired (client wants recursive resolution)
  RA: Recursion Available (server supports recursion)
  RCODE: Response code
    0 = NOERROR (success)
    1 = FORMERR (format error)
    2 = SERVFAIL (server failure)
    3 = NXDOMAIN (domain doesn't exist)
    5 = REFUSED (server refuses query)
```

---

## DNS Security

```
DNS CACHE POISONING (Kaminsky Attack, 2008):

  The attack:
  1. Attacker floods recursive resolver with forged
     responses for example.com
  2. Forged responses say:
     "example.com is at [attacker's IP]"
  3. If a forged response arrives BEFORE the real response
     AND has the correct Transaction ID...
  4. Resolver caches the FAKE answer
  5. ALL users of that resolver now go to attacker's server

  Original Transaction ID: 16 bits = 65,536 possibilities
  Attacker sends 65,536 guesses quickly → high success rate

  FIX: Source port randomization
  → Transaction ID (16 bits) + random source port (16+ bits)
  → ~32+ bits of entropy → much harder to guess
  → ALL modern resolvers do this

DNSSEC (DNS Security Extensions):

  Adds cryptographic signatures to DNS responses.

  Zone owner signs records with a private key.
  Resolvers verify signatures with the public key.
  Chain of trust: root → TLD → domain

  If an attacker forges a response:
  → Signature won't match
  → Resolver rejects it

  REALITY: DNSSEC adoption is still partial.
  Many domains don't sign. Many resolvers don't validate.
  But critical infrastructure (government, banking)
  increasingly requires it.

DNS OVER HTTPS (DoH) / DNS OVER TLS (DoT):

  Traditional DNS: plaintext UDP
  → ISP can see every domain you visit
  → Anyone on the network can see your DNS queries
  → Coffee shop WiFi? Your DNS is visible.

  DoH: DNS queries wrapped in HTTPS (port 443)
  → Encrypted, looks like normal HTTPS traffic
  → Can't be blocked without blocking all HTTPS
  → Used by: Chrome, Firefox, iOS, Android
  → Resolver: Cloudflare (1.1.1.1), Google (8.8.8.8)

  DoT: DNS queries over TLS (port 853)
  → Encrypted, but on a dedicated port
  → Easier to identify and block than DoH
  → Used by: Android (Private DNS setting)

  SRE IMPACT:
  → DoH/DoT add latency (TLS handshake)
  → But subsequent queries reuse the TLS connection
  → Corporate environments may NOT want DoH
    (they need to see DNS for security monitoring)
  → Can cause split-brain: browser uses DoH to 8.8.8.8,
    but system resolver uses corporate DNS
  → Internal domains (corp.example.com) may not resolve
    through external DoH resolvers
```

---

## The Facebook Outage — October 4, 2021

This is the most instructive DNS outage in internet history. Understanding it deeply is essential.

```
WHAT HAPPENED (step by step):

1. TRIGGER: Routine BGP maintenance
   Facebook engineers issued a command to assess
   the capacity of their backbone network.

   A bug in the audit tool accidentally WITHDREW
   the BGP routes that contained Facebook's DNS
   nameserver IP addresses.

2. BGP WITHDRAWAL:
   Facebook's authoritative DNS nameservers
   (a]ns.facebook.com, b.ns.facebook.com, etc.)
   ran on IPs like 129.134.30.12.

   The BGP withdrawal told the internet:
   "The route to 129.134.0.0/16 no longer exists."

   Within minutes, routers worldwide removed the
   route to Facebook's DNS servers.

3. DNS FAILURE CASCADE:

   User queries: facebook.com
   → Recursive resolver asks TLD server for .com
   → TLD says: "Ask ns1.facebook.com (129.134.30.12)"
   → Resolver tries to reach 129.134.30.12
   → UNREACHABLE (no BGP route exists)
   → Resolver tries ns2.facebook.com → also unreachable
   → All nameservers unreachable
   → Returns SERVFAIL to user

   facebook.com, instagram.com, whatsapp.com,
   messenger.com, oculus.com — ALL shared the same
   nameservers. ALL went down simultaneously.

4. GLOBAL AMPLIFICATION:

   Every resolver worldwide had cached Facebook DNS
   records with TTLs. As TTLs expired:
   → Resolver tries to refresh → SERVFAIL
   → Resolver removes cached record
   → User gets NXDOMAIN or SERVFAIL
   → User retries → more DNS queries → more SERVFAIL

   DNS query volume for facebook.com increased 30x
   across the internet. This overloaded some recursive
   resolvers, affecting DNS for OTHER domains too.

5. WHY IT TOOK 6 HOURS TO FIX:

   Here's the devastating part:

   → Facebook engineers couldn't remotely access
     their data centers (remote access tools used
     DNS that was down!)
   → Facebook's internal tools (used for network
     management) also depended on DNS → also down
   → Physical access to data centers was required
   → Badges/physical access systems partially
     depended on network services → complications
   → Had to physically go to data centers and
     manually reconfigure routers
   → Then: BGP routes had to propagate globally
     (takes ~20-30 minutes)
   → Then: DNS caches had to repopulate
   → Then: services had to restart and recover state

LESSONS:

  1. DNS is a SINGLE POINT OF FAILURE for everything.
     If your DNS is down, your monitoring, alerting,
     remote access, deployment tools — ALL are down.

  2. Out-of-band access is essential.
     You MUST have a way to access infrastructure
     that does NOT depend on DNS.
     → Direct IP-based SSH access
     → Dedicated management network
     → Phone-based authentication for physical access

  3. DNS and BGP are deeply intertwined.
     BGP carries the routes to reach DNS servers.
     If BGP routes are withdrawn, DNS servers become
     unreachable even though they're running fine.

  4. Shared DNS infrastructure = shared fate.
     Facebook, Instagram, WhatsApp, Messenger all
     used the same nameservers.
     One failure → all products down.
     Consider separate DNS infrastructure for
     independent products.

  5. Automation without safety rails is dangerous.
     The BGP change was automated. The tool didn't
     verify "will this make our DNS unreachable?"
     before executing.
```

---

## Decision Framework

```
DNS RECORD TYPE CHOOSER:

  Stable IP, health-checked failover           → A/AAAA + Route 53 failover routing
  Load-balanced endpoints change frequently    → CNAME/ALIAS (never CNAME at apex without ALIAS)
  Service discovery inside K8s                 → CoreDNS ClusterIP; external via Ingress/LB
  Geo/latency routing                          → Route 53 latency or geolocation policies
  Certificate validation                       → CNAME for ACM DNS validation

TTL POLICY:
  Infrastructure you control + fast failover   → TTL 60s or lower
  Stable CDN/origin                            → TTL 300–3600s
  Never change TTL during incident without plan  → low TTL + cache = resolver stampede
```

---

---

## Production Failure Patterns

### Failure 1: TTL Misconfiguration During Migration

```
SCENARIO:
  Migrating api.example.com from old server (1.1.1.1)
  to new server (2.2.2.2).

  Current TTL: 86400 (24 hours).

  Engineer changes A record from 1.1.1.1 to 2.2.2.2.
  Immediately shuts down old server.

  Result:
  → Resolvers that cached recently → still return 1.1.1.1
  → Those users connect to dead server → connection refused
  → For up to 24 HOURS
  → Only users whose cache expired get the new IP

  You just took down your API for up to 24 hours
  for a significant portion of users.

HOW TO DETECT:
  → "Some users can reach us, others can't"
  → Geographic pattern (ISPs expire at different times)
  → dig from different resolvers shows different answers:
    dig @8.8.8.8 api.example.com   → 1.1.1.1 (stale!)
    dig @1.1.1.1 api.example.com   → 2.2.2.2 (fresh)

CORRECT MIGRATION PROCESS:
  1. WEEKS before migration: lower TTL to 60s
     → Wait 24 hours for old TTL to expire everywhere
  2. Verify TTL propagation:
     dig api.example.com → check TTL in response
  3. Change A record from 1.1.1.1 to 2.2.2.2
  4. Wait 60 seconds (new TTL duration)
  5. Verify from multiple resolvers:
     dig @8.8.8.8 api.example.com → should show 2.2.2.2
     dig @1.1.1.1 api.example.com → should show 2.2.2.2
  6. Keep old server running for 1 hour (safety margin)
  7. Decommission old server
  8. Raise TTL back to desired value
```

### Failure 2: NXDOMAIN Storm in Kubernetes

```
SCENARIO:
  Microservice platform with 500 pods.
  Each pod makes 200 external API calls/second.
  ndots: 5 (Kubernetes default).

  Each external call generates 4 DNS queries
  (3 NXDOMAIN + 1 success).

  500 pods × 200 calls × 4 queries = 400,000 DNS
  queries per second hitting CoreDNS.

  CoreDNS pods have 2 CPU cores allocated.
  CoreDNS maxes out CPU → starts dropping queries.
  DNS latency spikes from 1ms to 500ms.
  EVERY microservice slows down (all need DNS).

  Looks like a network issue. Actually a DNS issue.

HOW TO DETECT:
  → CoreDNS CPU at 100%
  → CoreDNS metrics show high NXDOMAIN rate:
    coredns_dns_responses_total{rcode="NXDOMAIN"} >>>
    coredns_dns_responses_total{rcode="NOERROR"}
  → Pod DNS resolution time spikes
  → All services slow, not just one
  → Latency correlates with DNS resolution time

FIX:
  → Lower ndots to 2:
    dnsConfig:
      options:
        - name: ndots
          value: "2"

  → Deploy NodeLocal DNSCache:
    → DaemonSet runs DNS cache on every node
    → Pods query local cache instead of CoreDNS pods
    → Reduces CoreDNS load by 80-90%
    → NXDOMAIN responses cached locally

  → Use FQDNs for external services:
    → "api.stripe.com." (trailing dot)
    → Skips search domain attempts entirely
    → Zero wasted NXDOMAIN queries

  → Scale CoreDNS:
    → Increase replica count
    → Increase CPU/memory limits
    → Enable autopath plugin (reduces search domain queries)
```

### Failure 3: Java DNS Caching (The Silent Killer)

```
SCENARIO:
  Java microservice uses AWS RDS database.
  RDS endpoint: mydb.abc123.us-east-1.rds.amazonaws.com
  RDS fails over to a standby (IP changes).

  All OTHER services (Python, Go, Node) reconnect
  within 60 seconds.

  The Java service NEVER reconnects. It keeps trying
  the OLD IP address forever.

ROOT CAUSE:
  Java's default DNS cache TTL for POSITIVE lookups
  is INFINITE when a SecurityManager is installed.

  Even without SecurityManager, the default is 30 seconds
  in modern JVMs — but many enterprise configurations
  override this.

  The java.security file may contain:
    networkaddress.cache.ttl=-1  (cache forever!)

  The JVM caches the first DNS resolution and NEVER
  re-resolves. When the IP changes, Java doesn't know.

HOW TO DETECT:
  → Java services can't connect, all others can
  → "Connection refused" to an IP that's no longer valid
  → dig shows the correct NEW IP
  → But the Java process still connects to the OLD IP
  → jcmd or JMX shows cached DNS entries with old IP

FIX:
  → Set TTL in JVM arguments:
    -Dsun.net.inetaddr.ttl=60
    -Dsun.net.inetaddr.negative.ttl=10

  → Or in java.security file:
    networkaddress.cache.ttl=60
    networkaddress.cache.negative.ttl=10

  → Or programmatically:
    java.security.Security.setProperty(
      "networkaddress.cache.ttl", "60");

  → AWS specifically documents this:
    "If your application uses Java, set the JVM TTL"
    https://docs.aws.amazon.com/sdk-for-java/v1/developer-guide/java-dg-jvm-ttl.html

  This is one of the most common Java production issues
  when using cloud services with dynamic IPs.
```

### Failure 4: DNS Provider as Single Point of Failure

```
SCENARIO:
  Your domain uses a single DNS provider (say, Route 53).
  Route 53 experiences an outage in your region.

  ALL your domains are unreachable.
  Website, API, email — everything.

WHY THIS IS ESPECIALLY DANGEROUS:
  → You can't even switch DNS providers quickly!
  → To switch providers, you update NS records at
    the registrar
  → But registrar changes propagate via DNS
  → Which is currently broken
  → Catch-22: Need DNS to fix DNS

FIX — MULTI-PROVIDER DNS:

  example.com.  NS  ns1.route53.amazonaws.com.  (AWS)
  example.com.  NS  ns1.cloudflare.com.          (Cloudflare)

  Both providers serve the same records.
  If one goes down, the other still answers.

  COMPLEXITY:
  → Must keep records synchronized across providers
  → Tools: OctoDNS, DNSControl (infrastructure-as-code
    for DNS)
  → Changes must be applied to BOTH providers atomically
  → Health checking and failover between providers

  WHO DOES THIS:
  → Netflix (Route 53 + their own DNS)
  → GitHub (multiple providers)
  → Any company where DNS downtime = significant revenue loss
```

---

## SRE Diagnostic Toolkit

```
DIG — THE ESSENTIAL DNS TOOL:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Basic lookup
dig example.com
# Returns: A record, TTL, response time,
#          which server answered

# Query specific record type
dig example.com AAAA          # IPv6
dig example.com MX            # Mail servers
dig example.com NS            # Name servers
dig example.com TXT           # TXT records
dig example.com CNAME         # Aliases
dig example.com SOA           # Zone metadata
dig example.com ANY           # All records (often blocked)

# Query a SPECIFIC resolver (critical for debugging)
dig @8.8.8.8 example.com     # Ask Google DNS
dig @1.1.1.1 example.com     # Ask Cloudflare
dig @ns1.example.com example.com  # Ask authoritative directly

# Trace the FULL resolution path (shows every step)
dig +trace example.com
# Shows: root → TLD → authoritative → answer
# ESSENTIAL for debugging delegation issues

# Short output (just the answer)
dig +short example.com
# Output: 93.184.216.34

# Check TTL remaining
dig example.com | grep -A1 "ANSWER SECTION"
# Output: example.com.  237  IN  A  93.184.216.34
#                        ^^^
#                        237 seconds remaining in cache

# Check if response is authoritative
dig example.com | grep "flags"
# "flags: qr rd ra" = recursive answer (from cache)
# "flags: qr aa rd" = authoritative answer (from source)

# Reverse DNS lookup
dig -x 93.184.216.34
# Returns PTR record: the domain for this IP

# Check DNSSEC
dig +dnssec example.com
# Returns RRSIG records if DNSSEC is enabled


NSLOOKUP (simpler, less powerful):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

nslookup example.com
nslookup example.com 8.8.8.8    # specific resolver
nslookup -type=MX example.com   # specific record type


HOST (simplest):
━━━━━━━━━━━━━━━

host example.com
host -t MX example.com


PRODUCTION DEBUGGING WORKFLOW:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Step 1: Does the domain resolve at all?
dig +short api.example.com
# Empty = NXDOMAIN or SERVFAIL

# Step 2: What's the error?
dig api.example.com | grep "status"
# status: NOERROR  = resolved successfully
# status: NXDOMAIN = domain doesn't exist
# status: SERVFAIL = nameserver failed
# status: REFUSED  = nameserver refused query

# Step 3: Is it a caching issue?
# Compare cached vs authoritative:
dig api.example.com                        # cached (your resolver)
dig @ns1.example.com api.example.com       # authoritative (source)
# If different → propagation delay (TTL hasn't expired)

# Step 4: Is the delegation chain intact?
dig +trace api.example.com
# If trace stops at TLD → NS records missing/wrong
# If trace stops at authoritative → record doesn't exist
# If trace completes → record exists at authoritative

# Step 5: Check from multiple global locations
# Use online tools or:
dig @8.8.8.8 api.example.com       # Google (US)
dig @1.1.1.1 api.example.com       # Cloudflare (global anycast)
dig @9.9.9.9 api.example.com       # Quad9 (global)
dig @208.67.222.222 api.example.com # OpenDNS (Cisco)

# Step 6: In Kubernetes — check CoreDNS
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=100
kubectl top pods -n kube-system -l k8s-app=kube-dns

# Check what a specific pod resolves:
kubectl exec -it <pod-name> -- nslookup user-service
kubectl exec -it <pod-name> -- cat /etc/resolv.conf
```

---

## Hands-On Exercises

```
EXERCISE 1: Trace a Full DNS Resolution
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Watch every step of DNS resolution in real time:
  dig +trace google.com

  # You'll see:
  # 1. Root servers (.) responding with .com NS records
  # 2. .com TLD servers responding with google.com NS records
  # 3. Google's authoritative servers responding with
  #    the actual A record
  #
  # Count the hops. Note the TTLs at each level.
  # This is what happens for EVERY first-time DNS lookup.


EXERCISE 2: See TTL In Action
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Query a domain and watch TTL count down:
  dig example.com | grep -A1 "ANSWER"
  # Note the TTL (e.g., 300)

  # Wait 30 seconds and query again:
  sleep 30 && dig example.com | grep -A1 "ANSWER"
  # TTL should be ~270 now (300 - 30)

  # This proves your resolver is caching and
  # decrementing the TTL.

  # When TTL hits 0 → resolver queries authoritative
  # server again.


EXERCISE 3: See the Kubernetes ndots Problem
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Inside a Kubernetes pod:
  kubectl exec -it <any-pod> -- sh

  # Check resolv.conf:
  cat /etc/resolv.conf
  # Note: ndots:5 and the search domains

  # Now enable DNS query logging on CoreDNS:
  kubectl edit configmap coredns -n kube-system
  # Add "log" to the Corefile

  # From the pod, resolve an external domain:
  nslookup api.stripe.com

  # Check CoreDNS logs:
  kubectl logs -n kube-system -l k8s-app=kube-dns | \
    grep stripe

  # You'll see MULTIPLE queries:
  # api.stripe.com.default.svc.cluster.local → NXDOMAIN
  # api.stripe.com.svc.cluster.local → NXDOMAIN
  # api.stripe.com.cluster.local → NXDOMAIN
  # api.stripe.com → SUCCESS

  # 4 queries for 1 lookup! Now you see the problem.

  # Try with trailing dot:
  nslookup api.stripe.com.
  # Check logs → only 1 query! The trailing dot fixes it.


EXERCISE 4: Compare DNS Across Resolvers
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # See if different resolvers give different answers:
  echo "=== Google ===" && dig +short @8.8.8.8 example.com
  echo "=== Cloudflare ===" && dig +short @1.1.1.1 example.com
  echo "=== Quad9 ===" && dig +short @9.9.9.9 example.com
  echo "=== OpenDNS ===" && dig +short @208.67.222.222 example.com

  # If answers differ → propagation in progress or
  # GeoDNS returning location-specific answers
```

---

## Targeted Reading

```
REQUIRED:
  DDIA doesn't cover DNS deeply.

  Instead, read:
  1. Facebook's post-mortem of the October 2021 outage:
     "More details about the October 4 outage"
     https://engineering.fb.com/2021/10/05/networking-traffic/outage-details/
     → 15 minute read
     → Covers BGP + DNS interaction precisely
     → Best real-world DNS incident analysis available

  2. Cloudflare Blog: "What is DNS?"
     https://www.cloudflare.com/learning/dns/what-is-dns/
     → Excellent visual explanation
     → Covers record types, resolution process, caching

OPTIONAL (if targeting infrastructure companies):
  3. RFC 1035 (the DNS specification) — Sections 3 and 4 only
     → Dense but canonical
     → Gives you "I've read the RFC" credibility
```

---

## Ops Sim: Northstar Checkout DNS Failover That Did Not Fail Over

**Time box:** 30 minutes
**Severity:** P1
**Service / domain:** Route 53, CoreDNS, service discovery
**Northstar system:** Edge, API, Checkout

### Rules

1. Answer from memory; do not re-read the DNS section mid-drill.
2. Write decisions in order (T+0 -> T+60).
3. Cite the exact DNS/telemetry evidence behind each claim.
4. Do not open the answer key until finished.

### 1. Scenario stem

```text
WHAT USERS SEE:
  30% of checkout traffic still lands in a degraded us-east-1 ALB after failover
  to us-west-2 was declared complete.

WHAT ON-CALL SEES:
  Route 53 health check marked us-east-1 unhealthy at 12:03.
  Some clients still resolve the old ALB name at 12:47.
  Internal services also show lookup timeouts to `checkout-api`.

BUSINESS CONSTRAINT:
  You may keep reads in us-east-1, but new checkout writes must avoid the
  degraded ALB. A second failover mistake could double-charge customers.
```

### 2. Telemetry pack

```text
METRICS:
  Route53 health check us-east-1: unhealthy since 12:03
  public DNS answer old ALB by resolver:
    8.8.8.8=old, 1.1.1.1=new, 9.9.9.9=new, ISP-X=old
  authoritative TTL for checkout.northstar.example: 300s
  previous TTL before sale runbook: 3600s
  CoreDNS CPU: 94%; QPS 55k -> 410k; NXDOMAIN 61%
  checkout-api error rate by target ALB: old=19%, new=0.4%

LOG LINES:
  JVM checkout-worker: networkaddress.cache.ttl = -1
  CoreDNS: [ERROR] plugin/errors: 2 checkout-api.svc.us-east-1. A: i/o timeout
  app: lookup checkout-api on 10.100.0.10:53: read udp timeout

TRACE:
  internal order-confirmation -> bare hostname `checkout-api` -> 5 search suffix attempts
```

### 3. Config pack

```yaml
# Route 53 failover record
checkout.northstar.example:
  ttl_seconds: 300
  primary: dualstack.checkout-use1-alb.amazonaws.com
  secondary: dualstack.checkout-usw2-alb.amazonaws.com

# wrong/dangerous JVM and pod config
java:
  networkaddress.cache.ttl: -1
pod_dns:
  ndots: 5
service_url: "checkout-api"   # should be FQDN or service DNS with namespace
```

### 4. Timeline & decision points

| Time | Event | Your move (write before reading further) |
|------|-------|------------------------------------------|
| T+0 | P1: Route 53 failover happened, but 30% still hits old ALB. | |
| T+5 | You find JVM infinite DNS cache and ISP resolver stale answers. | |
| T+15 | A team proposes deleting the old ALB DNS record immediately. | |
| T+60 | Public stale traffic is down to 4%; CoreDNS is still near saturation. | |

### 5. Questions

**Q1 - Layer & root cause:** Separate public DNS cache staleness from internal CoreDNS amplification.

**Q2 - Evidence:** Which signals prove stale recursive/client caches? Which prove internal resolver overload?

**Q3 - Sequencing:** What do you do first to stop new checkout writes from old ALB?

**Q4 - Bad fix gallery:** Why is deleting the old ALB record dangerous? Why is "wait for TTL" incomplete?

**Q5 - Capacity / blast radius:** With `ndots:5`, how many queries can one bare-name lookup generate? What happens at 80k lookups/sec?

**Q6 - Durable fix:** What TTL, JVM, and Kubernetes DNS standards go into the runbook?

**Q7 - Org / runbook:** Who gets P1 comms, and what failover action is pre-authorized?

**Answer key:** [`../answers/Week-01-Transport-Application-Protocols-DNS-CDN/DNS Resolution Answers.md`](../answers/Week-01-Transport-Application-Protocols-DNS-CDN/DNS%20Resolution%20Answers.md)

---

## Key Takeaways

```
╔══════════════════════════════════════════════════════════════╗
║   IF YOU FORGET EVERYTHING ELSE, REMEMBER THESE:             ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. DNS resolution follows a strict hierarchy:              ║
║      Browser cache → OS cache → Recursive resolver           ║
║      → Root → TLD → Authoritative.                           ║
║      A failure at ANY level breaks resolution.               ║
║                                                              ║
║   2. TTL controls how long DNS is cached.                    ║
║      ALWAYS lower TTL BEFORE making DNS changes.             ║
║      Not doing this is the #1 DNS operational                ║
║      mistake.                                                ║
║                                                              ║
║   3. DNS is a SINGLE POINT OF FAILURE for everything.        ║
║      If DNS is down, monitoring, alerting, remote            ║
║      access, and deployment tools are ALSO down.             ║
║      Plan out-of-band access that doesn't need DNS.          ║
║                                                              ║
║   4. In Kubernetes, ndots:5 causes 3-4 wasted DNS            ║
║      queries per external lookup. At scale, this             ║
║      overwhelms CoreDNS. Use trailing dots on FQDNs          ║
║      or lower ndots.                                         ║
║                                                              ║
║   5. Java caches DNS forever by default.                     ║
║      Set networkaddress.cache.ttl=60 or you will             ║
║      get burned during failovers. This is not                ║
║      optional for cloud deployments.                         ║
╚══════════════════════════════════════════════════════════════╝
```

---

# 🔥 SRE SCENARIO — DNS

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1
Service: Global e-commerce platform
Time: 11:30 AM (Black Friday — peak traffic)

ARCHITECTURE:
  customers use: shop.example.com

  DNS: Route 53 with latency-based routing
    → US users    → us-east ALB  (Virginia)
    → EU users    → eu-west ALB  (Ireland)
    → Asia users  → ap-ne ALB    (Tokyo)

  TTL on shop.example.com: 60 seconds

  Backend:
    Each region has its own application cluster
    and database (primary in US, read replicas
    in EU and Asia)

INCIDENT TIMELINE:
  11:30 — Platform team deploys a database migration
          in US-East that requires 10 minutes of
          downtime for the US primary database

  11:30 — Team updates Route 53 to remove the US-East
          ALB from DNS, expecting all traffic to
          failover to EU-West and AP-NE

  11:31 — US customer complaints start flooding in
          "Can't access the website"
          "Connection refused"
          "Page won't load"

  11:35 — ~40% of US users still can't access the site

  11:40 — 10 minutes after DNS change, ~15% of US users
          still hitting the old US-East IP

  11:42 — SRE team notices something strange:
          Their Java-based inventory service (running in
          EU-West, handling redirected US traffic) is
          still trying to connect to the US-East database
          endpoint (db-primary.internal.example.com)
          which is currently down for migration

          The inventory service was restarted 3 days ago.
          The database endpoint IP changed when the
          migration began (RDS failover to a standby).

  11:45 — EU-West and AP-NE regions, now handling 3x
          their normal traffic, start showing elevated
          latency. CoreDNS in the EU Kubernetes cluster
          shows CPU at 98%.

  MONITORING DATA:
  → dig @8.8.8.8 shop.example.com from US → sometimes
    returns old US-East IP, sometimes EU-West IP
  → dig @ns1.route53.amazonaws.com shop.example.com
    → correctly returns only EU-West and AP-NE IPs
  → Inventory service logs:
    "Connection refused: 10.0.1.50:5432"
    (10.0.1.50 is the OLD database IP)
  → EU Kubernetes cluster: pods making external API
    calls to payment processor (payments.stripe.com)
    showing 500ms DNS resolution time (normally 2ms)
  → CoreDNS query rate: 850,000 queries/sec
    (normally 200,000/sec)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Question 1:** There are THREE separate DNS-related problems in this incident. Identify all three, explain the root cause of each, and cite the specific monitoring data that reveals each problem.

**Question 2:** For the 40% of US users still hitting the old IP at 11:35 (5 minutes after the DNS change with TTL=60): explain precisely why they haven't failed over yet, given that the TTL is only 60 seconds.

**Question 3:** Immediate mitigation for each of the three problems. Specific actions and commands.

**Question 4:** How should this maintenance window have been planned to avoid ALL three problems? Give me the step-by-step runbook that should have been followed.
> **Answer key (do not open until you attempt the scenario questions):**
> [`../answers/Week-01-Transport-Application-Protocols-DNS-CDN/DNS%20Resolution%20Answers.md`](../answers/Week-01-Transport-Application-Protocols-DNS-CDN/DNS%20Resolution%20Answers.md)
