# Answer Key - CDN Fundamentals

> Open only after attempting the learner file Ops Sim.

## Ops Sim: Northstar CloudFront Personalized Cache Leak

### Q1 - Layer & root cause

The CDN cached personalized checkout HTML under a cache key that ignored cookies, headers, and query strings. Because the response had `Cache-Control: public, s-maxage=600` while also setting a session cookie and rendering address data, CloudFront served one user's HTML to other sessions.

### Q2 - Evidence

Confirming signals:
1. `x-cache: Hit from cloudfront` on `/checkout/review`.
2. Cache behavior for `/checkout/*` has no cookies/headers/query strings in the cache key.
3. App log shows rendered user and session user mismatch.

Dangerous "good" metric: cache hit rate jumping to 94% and origin RPS dropping. For personalized pages, a high hit rate can mean data leakage.

### Q3 - First 15 minutes

1. Declare security/privacy P1.
2. Disable CDN caching for `/checkout/*` and account/session-bound HTML; force origin for those paths.
3. Invalidate affected paths broadly enough: `/checkout/*`, not just one URL.
4. Set origin headers to `Cache-Control: private, no-store` for personalized HTML.
5. Confirm `x-cache=Miss/Bypass` and no further mismatched render logs.
6. Preserve evidence/logs for privacy review and scope affected sessions.

### Q4 - Bad fixes

Purging one URL is insufficient because every personalized checkout/account path with the same bad policy can leak, and new responses can be cached again while the bad behavior remains.

Adding Cookie to the cache key for checkout HTML is risky because it creates unbounded cache cardinality, may still mishandle auth/session variation, and keeps sensitive HTML at the edge. Checkout/account HTML should usually be `private, no-store`.

### Q5 - Capacity / blast radius

```text
origin safe capacity = 22k RPS
bypass load = 18k RPS
headroom = 4k RPS ~= 18%
```

Watch origin CPU, connection pools, PgBouncer/Postgres, latency, autoscaling lag, and error budget. Consider serving static assets and non-personal catalog pages from CDN while bypassing only sensitive HTML.

### Q6 - Durable fix

- Default deny caching for any route that sets cookies or renders user data.
- Cache public catalog/static assets on versioned URLs.
- CI checks fail if `Set-Cookie` appears with `public`/`s-maxage`.
- Canary compares cache status for authenticated pages.
- Security review required for CloudFront cache-policy changes.

Acceptance: authenticated checkout/account pages never return `Hit from cloudfront`; public catalog hit rate remains healthy.

### Q7 - Org / runbook

Inform incident commander, security/privacy, legal, checkout owner, support, and communications.

Pre-authorized: disable edge caching for sensitive paths, invalidate broad sensitive path patterns, and raise origin capacity. Escalate before customer notifications, forensic data export, or changing retention.
# Answer Key — CDN Fundamentals

> Open only after attempting the learner file questions.

---

# Incident Deep-Dive: CDN Cache Poisoning — PII Exposure

---

## Question 1: The Exact Sequence — From Deployment to Data Breach

### Tracing the Timeline, Request by Request

```
3:10:00 PM — Deployment goes out.
  The account_dashboard controller now returns:
    Cache-Control: public, s-maxage=300
  Instead of:
    Cache-Control: private, no-cache

  At this moment, nothing is broken yet.
  The CDN has no cached copy of /account/dashboard.
  The PREVIOUS cached version (if any) had
  Cache-Control: private, so Cloudflare never
  cached it. The CDN cache slot for this URL is EMPTY.
```

```
~3:10:XX PM — The FIRST user to request /account/dashboard
              after the deployment becomes the victim.

  User 88421 (let's call her Sarah) opens her browser
  and navigates to https://shop.example.com/account/dashboard

  REQUEST FLOW:

  Sarah's browser
    │
    ├─► GET /account/dashboard
    │   Cookie: session=sarah_session_token
    │
    ▼
  Cloudflare CDN Edge (e.g., Chicago POP)
    │
    │  Cloudflare checks its cache for /account/dashboard
    │  Cache key: scheme + host + path =
    │    "https://shop.example.com/account/dashboard"
    │  Result: CACHE MISS (no cached copy exists)
    │
    │  Cloudflare forwards the request to origin,
    │  INCLUDING Sarah's session cookie.
    │
    ├─► GET /account/dashboard
    │   Cookie: session=sarah_session_token
    │
    ▼
  Origin Application Server
    │
    │  The application:
    │    1. Reads sarah_session_token from the cookie
    │    2. Looks up Sarah's session → User ID 88421
    │    3. Queries database for Sarah's name, address,
    │       order history
    │    4. Renders dashboard.html with SARAH'S DATA
    │    5. Returns the response with the NEW cache header:
    │
    │  HTTP/2 200
    │  Content-Type: text/html
    │  Cache-Control: public, s-maxage=300   ← THE BUG
    │  Set-Cookie: session=abc123
    │  Vary: Accept-Encoding
    │  Body: <html>Welcome, Sarah! Your address:
    │        123 Main St... Order #4521: ...</html>
    │
    ▼
  Cloudflare CDN Edge
    │
    │  Cloudflare reads the response headers:
    │    Cache-Control: public, s-maxage=300
    │
    │  "public" → I AM ALLOWED to cache this
    │  "s-maxage=300" → Cache it for 300 seconds (5 min)
    │
    │  Cloudflare STORES Sarah's fully rendered account
    │  page in its edge cache:
    │    Cache key: "https://shop.example.com/account/dashboard"
    │    Cache value: Sarah's complete HTML (name, address, orders)
    │    TTL: 300 seconds
    │    Stored at: ~3:10 PM
    │    Expires at: ~3:15 PM
    │
    │  Cloudflare returns the response to Sarah.
    │  Sarah sees her own account page. Everything looks normal.
    │  Sarah has NO IDEA her data just got cached publicly.
    │
    ▼
  Sarah's browser renders her account page. ✓ Looks correct.
```

```
~3:10 to 3:15 PM — EVERY subsequent user gets Sarah's data.

  User 77210 (Bob) navigates to /account/dashboard.

  Bob's browser
    │
    ├─► GET /account/dashboard
    │   Cookie: session=bob_session_token
    │
    ▼
  Cloudflare CDN Edge
    │
    │  Cloudflare checks its cache for /account/dashboard
    │  Cache key: "https://shop.example.com/account/dashboard"
    │  Result: CACHE HIT ✓ (cached 187 seconds ago)
    │
    │  Cloudflare DOES NOT forward the request to origin.
    │  It doesn't even LOOK at Bob's cookie.
    │  It returns the cached response DIRECTLY:
    │
    │  HTTP/2 200
    │  Content-Type: text/html
    │  Cache-Control: public, s-maxage=300
    │  CF-Cache-Status: HIT        ← served from cache
    │  Age: 187                    ← cached 187 seconds ago
    │  Body: <html>Welcome, Sarah! Your address:
    │        123 Main St... Order #4521: ...</html>
    │
    ▼
  Bob's browser renders SARAH'S account page.
  Bob sees Sarah's name, address, order history.

  ✗ PERSONAL DATA BREACH
```

### Why User 88421 Specifically?

```
Sarah (User 88421) was not special. She was simply
the FIRST USER to request /account/dashboard after
the deployment at 3:10 PM that hit a Cloudflare edge
node with an empty cache slot for that URL.

If Bob had loaded the page 0.5 seconds before Sarah,
BOB'S data would be the cached version, and SARAH
would be the one seeing Bob's information.

The "victim" is determined by a RACE CONDITION:
  → First request after deployment + cache miss
    = that user's data becomes the cached version
  → Every subsequent request within the 300-second
    TTL serves that first user's data

This is also PER EDGE POP:
  → Cloudflare has 300+ Points of Presence worldwide
  → Each POP has its own independent cache
  → The "first user" at the Chicago POP might be Sarah
  → The "first user" at the London POP might be someone else
  → MULTIPLE users' PII may be exposed simultaneously
    at different edge locations
  → This makes the breach WORSE than it appears —
    it's not one victim, it's potentially 300+ victims
    (one per POP that received traffic after 3:10 PM)
```

### The Evidence in the curl Output

```
curl -sI https://shop.example.com/account/dashboard

HTTP/2 200
Content-Type: text/html
Cache-Control: public, s-maxage=300    ← THE ROOT CAUSE
                                         "public" = CDN may cache
                                         "s-maxage=300" = cache for 5 min
Set-Cookie: session=abc123             ← RED FLAG: setting a cookie
                                         on a cached response means
                                         the SESSION is being shared too
CF-Cache-Status: HIT                   ← PROOF: served from CDN cache,
                                         not from origin
Age: 187                               ← Cached 187 seconds ago
                                         (3 min 7 sec since first cache)
Vary: Accept-Encoding                  ← Only varies on encoding,
                                         NOT on Cookie/Authorization
                                         → all users get the same cache
```

---

## Question 2: Immediate Mitigation — Every Second Counts

This is a **SECURITY incident with active PII exposure**. Every second the cached content is served, another user potentially sees someone else's personal data. Priority is: **stop the bleeding, then clean up, then investigate.**

### Action 1: PURGE THE CDN CACHE — RIGHT NOW (Second 0-30)

```bash
# Purge the specific URL from ALL Cloudflare edge POPs worldwide
# This is the single fastest action to stop PII exposure.

curl -X POST "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/purge_cache" \
  -H "Authorization: Bearer $CF_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "files": [
      "https://shop.example.com/account/dashboard",
      "https://shop.example.com/account/orders",
      "https://shop.example.com/account/profile",
      "https://shop.example.com/account/addresses",
      "https://shop.example.com/account/payment-methods"
    ]
  }'

# Don't just purge /account/dashboard.
# The deployment changed the CONTROLLER — it likely
# affects ALL /account/* routes.
# Purge EVERY account-related URL.

# If unsure which URLs are affected, PURGE EVERYTHING:
curl -X POST "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/purge_cache" \
  -H "Authorization: Bearer $CF_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"purge_everything": true}'

# Yes, this will cause a temporary cache miss storm on origin.
# That is infinitely preferable to continuing to serve PII.
# You can deal with origin load AFTER the breach is stopped.
```

### Action 2: ROLL BACK THE DEPLOYMENT — Immediately After Purge (Second 30-90)

```bash
# The cache purge stops CURRENT exposure, but the origin
# is STILL returning Cache-Control: public, s-maxage=300.
# If you don't roll back, the NEXT request will re-populate
# the cache with another user's data.

# Roll back to the previous revision:
kubectl rollout undo deployment/web-application

# OR if using CI/CD:
# Trigger redeploy of the last known good artifact

# VERIFY the rollback:
curl -sI https://shop.example.com/account/dashboard \
  -H "Cookie: session=test_session"

# MUST show:
#   Cache-Control: private, no-cache
#   CF-Cache-Status: DYNAMIC (not HIT)
#
# If it still shows "public, s-maxage=300", the rollback
# hasn't propagated yet. Wait for pod rotation.
```

### Action 3: Activate Security Incident Response Protocol (Minute 2-5)

```
This is not just an engineering problem. This is a DATA BREACH.

IMMEDIATE NOTIFICATIONS (in parallel with technical mitigation):

  □ Security team / CISO
    → "Authenticated user PII served to unauthorized users
       via CDN cache. Active exposure from 3:10 to [purge time].
       Estimated impact: all users who visited /account/*
       during the window."

  □ Legal / DPO (Data Protection Officer)
    → GDPR Article 33: 72-hour notification deadline to
      supervisory authority if EU users affected
    → CCPA: notification requirements for CA users
    → Breach involved: names, addresses, order history,
      potentially payment method details

  □ Customer support team
    → Prepare for incoming reports
    → Script: "We identified a brief technical issue that
      may have displayed incorrect account information.
      We have resolved it. No passwords or payment card
      numbers were exposed."
      (Adjust based on what was ACTUALLY in the page)
```

### Action 4: Assess Blast Radius (Minute 5-15)

```bash
# Determine exactly which users' data was cached and
# which users SAW that data.

# Step 1: Check Cloudflare logs for all HIT responses
# on /account/* between 3:10 and purge time:

# Cloudflare Enterprise logs or Logpush:
# Filter:
#   path STARTS WITH "/account/"
#   AND CacheStatus = "hit"
#   AND timestamp BETWEEN "3:10 PM" AND "[purge time]"

# This tells you:
#   → HOW MANY requests were served cached PII
#   → FROM WHICH edge POPs (geographic impact)
#   → Client IPs (can correlate to affected users)

# Step 2: Identify the VICTIMS (users whose data was cached)
# The first MISS request to each POP after 3:10 = the victim
# Filter Cloudflare logs:
#   path STARTS WITH "/account/"
#   AND CacheStatus = "miss"
#   AND timestamp >= "3:10 PM"
#   ORDER BY timestamp ASC
#   GROUP BY EdgeColoID  (per POP)

# The first miss per POP → that user's data was cached
# Cross-reference with origin access logs to get User IDs

# Step 3: Identify VIEWERS (users who saw others' data)
# All subsequent HIT requests on the same POP in the same
# TTL window = users who saw the victim's data
```

### Mitigation Timeline Summary

```
╔══════════════════════════════════════════════════════════════╗
║  TIME   │ ACTION                          │ IMPACT           ║
╠══════════════════════════════════════════════════════════════╣
║  +0s    │ Purge CDN cache (all /account/* │ STOPS            ║
║         │ or purge_everything)            │ exposure         ║
╠══════════════════════════════════════════════════════════════╣
║  +30s   │ Roll back deployment            │ PREVENTS         ║
║         │                                 │ recurrence       ║
╠══════════════════════════════════════════════════════════════╣
║  +60s   │ Verify: Cache-Control: private  │ CONFIRMS         ║
║         │ CF-Cache-Status: DYNAMIC        │ fix              ║
╠══════════════════════════════════════════════════════════════╣
║  +2min  │ Notify security/legal/support   │ COMPLIANCE       ║
╠══════════════════════════════════════════════════════════════╣
║  +5min  │ Analyze logs for blast radius   │ SCOPE            ║
╠══════════════════════════════════════════════════════════════╣
║  +15min │ Notify affected users           │ TRUST            ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Question 3: The Vary Header — Why Accept-Encoding Didn't Help

### What the Vary Header Does

```
The Vary header tells the CDN:
"This response varies depending on the value of
[specified request header]. Create SEPARATE cache
entries for each unique value of that header."

The response has:
  Vary: Accept-Encoding

This means Cloudflare creates separate cache entries for:
  → Accept-Encoding: gzip       → cached copy A (gzipped)
  → Accept-Encoding: br         → cached copy B (brotli)
  → Accept-Encoding: identity   → cached copy C (uncompressed)

So the cache key becomes:
  "https://shop.example.com/account/dashboard" + Accept-Encoding value
```

### Why It DIDN'T Prevent the Problem

```
Vary: Accept-Encoding varies on COMPRESSION FORMAT,
not on USER IDENTITY.

When Bob requests /account/dashboard:
  Bob's request: Accept-Encoding: gzip
  Cache key: URL + "gzip"

  Sarah's cached entry was ALSO Accept-Encoding: gzip
  (virtually all modern browsers send identical
   Accept-Encoding headers)

  Cache key matches → CACHE HIT → Bob gets Sarah's data

  Bob and Sarah have different session cookies.
  But the Vary header doesn't include Cookie.
  So the CDN doesn't even LOOK at the cookie
  when computing the cache key.

  ╔══════════════════════════════════════════════════════════════╗
  ║   SARAH'S REQUEST:                                           ║
  ║     URL: /account/dashboard                                  ║
  ║     Accept-Encoding: gzip, br                                ║
  ║     Cookie: session=sarah_token                              ║
  ║                                                              ║
  ║   Cache key (what CDN uses):                                 ║
  ║     /account/dashboard + gzip,br                             ║
  ║                                                              ║
  ║   BOB'S REQUEST:                                             ║
  ║     URL: /account/dashboard                                  ║
  ║     Accept-Encoding: gzip, br                                ║
  ║     Cookie: session=bob_token       ← IGNORED                ║
  ║                                                              ║
  ║   Cache key (what CDN uses):                                 ║
  ║     /account/dashboard + gzip,br                             ║
  ║                                                              ║
  ║   SAME cache key. CDN serves Sarah's page.                   ║
  ╚══════════════════════════════════════════════════════════════╝
```

### What Vary Value WOULD Have Prevented It

```
Vary: Cookie

This would tell the CDN:
"Create a SEPARATE cache entry for each unique
Cookie header value."

  Sarah's request:
    Cookie: session=sarah_token
    Cache key: /account/dashboard + "session=sarah_token"
    → Cache MISS → fetch from origin → store Sarah's page

  Bob's request:
    Cookie: session=bob_token
    Cache key: /account/dashboard + "session=bob_token"
    → Cache MISS (different cookie = different key)
    → Fetch from origin → store Bob's page
    → Bob sees his OWN data ✓

  Each user gets their own cache entry.
  No cross-user data exposure.
```

### Why Vary: Cookie Is the WRONG Fix

```
╔══════════════════════════════════════════════════════════════╗
║   Vary: Cookie would PREVENT the security issue.             ║
║   But it would be the WRONG architectural fix.               ║
║                                                              ║
║   WHY:                                                       ║
║                                                              ║
║   1. CACHE EXPLOSION                                         ║
║      Every unique session cookie = a separate                ║
║      cache entry. If you have 1 million active               ║
║      users, you now have 1 million cached copies             ║
║      of /account/dashboard in the CDN.                       ║
║      That's not caching. That's a database.                  ║
║                                                              ║
║   2. NEAR-ZERO HIT RATE                                      ║
║      Session cookies are unique per user.                    ║
║      A cache entry per user means every request              ║
║      is a cache miss (users rarely reload the                ║
║      exact same page within 300 seconds).                    ║
║      You'd have CDN overhead with no CDN benefit.            ║
║                                                              ║
║   3. PRIVACY STILL AT RISK                                   ║
║      If a user's session cookie is predictable,              ║
║      rotated, or shared (SSO), cache collisions              ║
║      could still occur.                                      ║
║                                                              ║
║   THE CORRECT FIX:                                           ║
║      Authenticated user pages should NEVER be                ║
║      cached at the CDN layer. Period.                        ║
║                                                              ║
║      Cache-Control: private, no-store                        ║
║                                                              ║
║      "private" = only the user's browser may cache           ║
║      "no-store" = don't even store it in the                 ║
║                   browser cache (sensitive data)             ║
║                                                              ║
║      The original code had it right:                         ║
║        @CacheControl(private, no-cache)                      ║
║      The developer broke it by changing to public.           ║
║                                                              ║
║      The fix is not a smarter Vary header.                   ║
║      The fix is not caching this content AT ALL              ║
║      in shared caches.                                       ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Question 4: Long-Term Controls — Making This Bug Class Impossible

The root cause is a **single developer changing one annotation** and exposing PII to the entire internet. The fix cannot be "tell developers not to do this." Humans make mistakes. The system must make this class of mistake **structurally impossible.**

### Layer 1: CDN Edge — The Last Line of Defense

**Cloudflare Cache Rules: NEVER cache authenticated content regardless of origin headers.**

```
Cloudflare Dashboard → Caching → Cache Rules

Rule 1 (HIGHEST PRIORITY):
  IF:  URL path starts with "/account/"
  OR:  Request has Cookie header containing "session="
  OR:  Request has Authorization header
  THEN: Cache eligibility = BYPASS CACHE

  This rule overrides ANY Cache-Control header from origin.
  Even if the origin says "public, s-maxage=31536000",
  Cloudflare will NOT cache it.
```

```
# Cloudflare API equivalent:
curl -X POST "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/rulesets" \
  -H "Authorization: Bearer $CF_API_TOKEN" \
  -d '{
    "name": "Never cache authenticated content",
    "kind": "zone",
    "phase": "http_request_cache_settings",
    "rules": [
      {
        "expression": "(http.request.uri.path starts_with \"/account\") or (http.cookie contains \"session=\") or (http.request.headers[\"authorization\"] != \"\")",
        "action": "set_cache_settings",
        "action_parameters": {
          "cache": false
        }
      }
    ]
  }'
```

**Why this is the most critical control:**
```
This is a DEFENSE-IN-DEPTH layer that protects against
the EXACT scenario that occurred.

Even if a developer sets Cache-Control: public on an
authenticated page, the CDN rule OVERRIDES it.

The CDN is the last checkpoint before content reaches
users. If this layer enforces "never cache /account/*",
no code change can bypass it.
```

### Layer 2: Origin Application — Framework-Level Default

**Set secure-by-default Cache-Control headers at the framework/middleware level, not at the controller level.**

```python
# ✗ CURRENT: Cache-Control is set per-controller
# Any developer can change it. No guardrails.

@CacheControl(public, s_maxage=300)  # Developer "improves perf"
def account_dashboard(request):
    ...

# ✓ FIXED: Middleware enforces Cache-Control based on
# authentication state. Controllers CANNOT override.

class SecureCacheMiddleware:
    def process_response(self, request, response):
        # If the request is authenticated (has a session),
        # FORCE private, no-store regardless of what the
        # controller set
        if request.user.is_authenticated:
            response['Cache-Control'] = 'private, no-store, no-cache'
            response['Pragma'] = 'no-cache'
            # Remove any s-maxage that a controller might have set
            # This is the OVERRIDE — controllers cannot bypass this

            # Also: REMOVE Set-Cookie from cached responses
            # (Cloudflare should never cache a Set-Cookie response,
            #  but belt-and-suspenders)

        # If the request is unauthenticated AND the path
        # is in the safe-to-cache list, allow caching
        elif request.path in CACHEABLE_PATHS:
            # Let the controller's Cache-Control through
            pass

        else:
            # Default: private (safe default)
            response['Cache-Control'] = 'private, no-cache'

        return response
```

**The critical design principle:**
```
╔══════════════════════════════════════════════════════════════╗
║   SECURE BY DEFAULT, EXPLICITLY OPT IN TO CACHING            ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   ✗ Wrong model (current):                                   ║
║      Default: no cache header                                ║
║      Developer ADDS caching per route                        ║
║      Risk: developer adds caching to wrong route             ║
║                                                              ║
║   ✓ Correct model:                                           ║
║      Default: private, no-store for ALL authed               ║
║      requests                                                ║
║      Middleware ENFORCES this regardless of                  ║
║      controller annotations                                  ║
║      Caching is ONLY allowed for explicitly                  ║
║      whitelisted, unauthenticated paths                      ║
║                                                              ║
║   A developer cannot accidentally make an authed             ║
║   page cacheable because the middleware overrides            ║
║   any cache header they set.                                 ║
╚══════════════════════════════════════════════════════════════╝
```

### Layer 3: CI/CD Pipeline — Automated Detection

**Static analysis / linting rules that catch dangerous cache headers before deployment.**

```yaml
# .github/workflows/cache-safety-check.yml
name: Cache-Control Safety Check

on: [pull_request]

jobs:
  cache-safety:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Check for public cache on authenticated routes
        run: |
          # Find all controllers in /account/ routes that set
          # Cache-Control: public
          VIOLATIONS=$(grep -rn "@CacheControl.*public" \
            --include="*.py" --include="*.java" --include="*.ts" \
            app/controllers/account/ \
            app/controllers/user/ \
            app/controllers/checkout/ \
            app/controllers/payment/ || true)

          if [ -n "$VIOLATIONS" ]; then
            echo "✗ SECURITY VIOLATION: Public cache headers on authenticated routes"
            echo "$VIOLATIONS"
            echo ""
            echo "Authenticated routes (/account/*, /user/*, /checkout/*, /payment/*)"
            echo "MUST use Cache-Control: private, no-store"
            echo ""
            echo "If you believe this is a false positive, request a security review."
            exit 1
          fi

          echo "✓ No public cache headers on authenticated routes"
```

```yaml
      - name: Check for missing Cache-Control on new routes
        run: |
          # Any new controller that doesn't explicitly set
          # Cache-Control is flagged for review
          DIFF=$(git diff origin/main --name-only --diff-filter=A \
            -- 'app/controllers/**')

          for file in $DIFF; do
            if ! grep -q "CacheControl\|cache_control\|Cache-Control" "$file"; then
              echo "⚠️  WARNING: New controller $file has no explicit Cache-Control"
              echo "   All controllers MUST set Cache-Control explicitly."
              echo "   Authenticated routes: private, no-store"
              echo "   Public content: public, s-maxage=N"
              exit 1
            fi
          done
```

### Layer 4: Response Validation — Runtime Canary

**A continuous test that verifies the CDN is NOT caching authenticated content.**

```python
# Runs every 60 seconds in production monitoring
def test_account_page_not_cached():
    """
    SECURITY CANARY: Verify that account pages are never
    served from CDN cache.

    If this test fails, page immediately and purge CDN.
    """
    # Step 1: Make an authenticated request
    response = requests.get(
        "https://shop.example.com/account/dashboard",
        cookies={"session": CANARY_USER_SESSION_TOKEN}
    )

    # Step 2: Verify Cache-Control is private
    cache_control = response.headers.get("Cache-Control", "")
    assert "public" not in cache_control, \
        f"CRITICAL: /account/dashboard has Cache-Control: {cache_control}"
    assert "private" in cache_control or "no-store" in cache_control, \
        f"CRITICAL: /account/dashboard missing private/no-store: {cache_control}"

    # Step 3: Verify Cloudflare did NOT cache it
    cf_cache_status = response.headers.get("CF-Cache-Status", "")
    assert cf_cache_status != "HIT", \
        f"CRITICAL: /account/dashboard served from CDN cache! CF-Cache-Status: {cf_cache_status}"

    # Step 4: Verify response contains ONLY the canary user's data
    assert CANARY_USER_NAME in response.text, \
        "CRITICAL: /account/dashboard returned wrong user's data"

    # Step 5: Make an UNAUTHENTICATED request — should NOT
    # return any user data
    unauthed = requests.get(
        "https://shop.example.com/account/dashboard"
    )
    assert unauthed.status_code in (302, 401, 403), \
        f"CRITICAL: /account/dashboard accessible without auth: {unauthed.status_code}"


# Alert configuration:
# If this canary fails ONCE:
#   → P1 SECURITY alert to on-call
#   → Auto-trigger CDN purge via webhook
#   → Auto-rollback last deployment (if within 30 min window)
```

### Layer 5: Code Review — Human Guardrails

```
MANDATORY CODE REVIEW RULES:

  1. ANY change to Cache-Control, Vary, CDN config,
     or caching annotations requires review from
     the SECURITY team, not just the feature team.

  2. PR template includes a checkbox:
     □ This PR does not modify cache headers on
       authenticated routes
     □ If it DOES modify cache headers, security
       review is attached

  3. CODEOWNERS file enforces this:
     # .github/CODEOWNERS
     **/cache*.py          @security-team
     **/middleware/cache*   @security-team
     **/cdn/**              @security-team

     # Any file with CacheControl annotation changes
     # requires security review (enforced by CI check)
```

### Complete Defense-in-Depth Matrix

```
╔══════════════════════════════════════════════════════════════════════════╗
║  LAYER                  │ CONTROL                          │ CATCHES?    ║
╠══════════════════════════════════════════════════════════════════════════╣
║  CDN Edge (Cloudflare)  │ Never cache /account/* or        │ ✓ YES —     ║
║                         │ requests with session cookie;    │ ignores     ║
║                         │ bypass rule overrides origin     │ public CC   ║
╠══════════════════════════════════════════════════════════════════════════╣
║  Application Middleware │ Force private, no-store on ALL   │ ✓ YES —     ║
║                         │ authenticated responses          │ overrides   ║
║                         │ regardless of controller         │ annotation  ║
╠══════════════════════════════════════════════════════════════════════════╣
║  CI Pipeline            │ Static analysis: block PRs with  │ ✓ YES —     ║
║                         │ public cache on authed routes    │ PR blocked  ║
╠══════════════════════════════════════════════════════════════════════════╣
║  Runtime Monitoring     │ Canary: /account pages never     │ ✓ YES —     ║
║                         │ served from cache; alert +         │ detected  ║
║                         │ auto-purge on failure            │ in 60s      ║
╠══════════════════════════════════════════════════════════════════════════╣
║  Code Review            │ CODEOWNERS: cache changes need   │ ✓ YES —     ║
║                         │ security team signoff            │ required    ║
╠══════════════════════════════════════════════════════════════════════════╣
║  Default Posture        │ Framework default: private,      │ ✓ YES —     ║
║                         │ no-store for authenticated reqs  │ safe even   ║
║                         │                                  │ if all      ║
║                         │                                  │ else fail   ║
╚══════════════════════════════════════════════════════════════════════════╝

ANY SINGLE LAYER would have prevented this incident.
ALL layers together make it structurally impossible.

The developer's change would have been:
  1. Blocked at PR by CI static analysis
  2. Blocked at PR by CODEOWNERS security review
  3. Overridden at runtime by middleware
  4. Overridden at CDN by cache rules
  5. Detected in 60 seconds by canary test
  6. Auto-purged and auto-rolled back

SIX independent controls.
The developer would need to bypass ALL SIX
to cause this incident again.

That's defense in depth.
```

---

> **Retention test moved:** Week 1 rapid-fire + compound scenario (auction platform)
> are in [Retention-Tests/Week-01.md](../../Retention-Tests/Week-01.md) to keep this
> module topic-only per curriculum standards.
