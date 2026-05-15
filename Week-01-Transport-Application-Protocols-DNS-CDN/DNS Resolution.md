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
  → ~60% of users ✅

Category B: Users behind ISP resolvers with TTL floors
  → ISP applies 5-minute minimum TTL
  → Cache won't expire until 11:35 at earliest
  → Some ISP caches populated at 11:29 → expire 11:34 ✅
  → Some ISP caches populated at 11:30 → expire 11:35 ⚠️ BORDERLINE
  → Some ISP caches populated after 11:30 but before 
    the ISP's edge refreshed → still stale
  → ~20% of users ❌

Category C: Users behind corporate/local DNS with 
            minimum TTL floors of 10-15 minutes
  → Won't expire until 11:40-11:45
  → ~10% of users ❌

Category D: Users whose browser cache is hot
  → Visited the site in the last 60 seconds
  → Browser hasn't re-resolved yet
  → Small percentage, constantly rolling
  → ~5% of users ❌

Category E: Users with aggressive local caching
  → Home routers with dnsmasq min-cache-ttl=300+
  → Stale corporate proxy caches
  → ~5% of users ❌

  TOTAL AT 11:35:
    Category A:           60% → working ✅
    Categories B+C+D+E:   40% → still hitting old IP ❌
    
    MATCHES THE OBSERVED 40% EXACTLY.

AT 11:40 (T+10min):
    Category B (ISP 5-min floors) → mostly expired now ✅
    Category C (corporate 10-min floors) → still stale ❌
    Category D (browser) → long since expired ✅
    Category E (aggressive local) → some still stale ❌
    
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
