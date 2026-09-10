# Design Photo Sharing Platform (Instagram / Flickr) — Worked Answers

## Answer 1: POST vs. GET for Pre-Signed URL Intent

1. **State Mutation & Resource Reservation**:
   Requesting an upload intent is not an idempotent, read-only operation. The server creates a pending record in the database (`status = 'UPLOADING'`), reserves storage quota, and generates an ephemeral cryptographic token.
2. **Browser & Proxy Caching Defense**:
   HTTP `GET` requests are idempotent and aggressively cached by intermediate corporate proxies and browsers. If `GET` were used, a proxy might return a cached pre-signed URL previously issued to another user or an expired token.
3. **Payload Passing**:
   `POST` allows sending JSON metadata in the request body (image dimensions, mime type, declared byte size, client checksum) to pre-validate upload eligibility before generating the S3 lease.

---

## Answer 2: CDN Origin Shield Mechanics Against Thundering Herds

1. **The Edge Cache Stampede Problem**:
   When a celebrity posts a photo, hundreds of thousands of requests arrive simultaneously across 300+ global CDN Edge Point-of-Presence (PoP) locations. On an edge cache miss, all 300 PoPs would hit the central AWS S3 origin simultaneously, causing S3 503 Slow Down rate limit errors.
2. **Origin Shield Consolidation**:
   An **Origin Shield** is an intermediate, centralized caching tier positioned between regional edge PoPs and the S3 origin bucket.
3. **Request Coalescing (Singleflight at Edge)**:
   - When 300 Edge PoPs miss cache for `photo_123.webp`, they all forward their request to the Origin Shield.
   - The Origin Shield coalesces concurrent requests into **exactly ONE** request to the S3 bucket.
   - S3 serves 1 request; Origin Shield caches it and streams it back to the 300 Edge PoPs, reducing origin load by 99.9%.

---

## Answer 3: Avoiding Expensive CDN Purge API Calls on Deletions

1. **Cost of Wildcard Purging**:
   Cloud providers charge significant fees for bulk or frequent CDN cache invalidation API requests (e.g. AWS CloudFront charges $0.005 per path after the first 1,000 paths/month).
2. **Metadata Severing**:
   When a user deletes a photo, mark `status = 'DELETED'` in the photo metadata database immediately:
   - The photo disappears from feeds, search results, and user profiles in < 10ms.
   - Users cannot discover the photo link.
3. **Content-Addressed Immutability**:
   Because the media URL contains an unguessable UUID/hash (e.g. `p/7b2401f8_1080.webp`), an attacker cannot guess the direct URL.
4. **Natural TTL Expiration + Lazy S3 Object Deletion**:
   Let the cached file naturally expire from edge caches via its `Cache-Control: max-age` header, and issue an asynchronous S3 deletion lifecycle marker without triggering costly synchronous CDN purge requests.
