# Answer Key - Week 9: Design URL Shortener TinyURL

> Open only after attempting the learner file scenario questions.

## Principal Model Answer & Interview Evaluation Matrix

```
╔═════════════════════════════════════════════════════════════════════════════╗
║ PRINCIPAL MODEL ANSWER SUMMARY — DISTRIBUTED URL SHORTENER TINYURL          ║
╠═════════════════════════════════════════════════════════════════════════════╣
║ 1. Base62 encoding yields 3.52 Trillion 7-character collision-free keys.    ║
║ 2. KGS range leasing (1M blocks via etcd) eliminates DB uniqueness checks   ║
║ 3. HTTP 302 preserves 100% click analytics and enables instant link revokes.║
║ 4. Redis Bloom filter in RAM blocks 99.9% of cache penetration attacks.     ║
║ 5. Decoupled Kafka clickstream pipeline streams telemetry to ClickHouse.    ║
╚═════════════════════════════════════════════════════════════════════════════╝
```

---

## Detailed Model Solutions to Section 9 Practice Drills

### Q1: Base62 Mathematical Encoding Mechanics
* **Bijective Base Conversion:** Any positive 64-bit integer $N$ maps bijectively to a Base62 string via repeated division:
  $$	ext{Remainder} = N \pmod{62}, \quad N = \lfloor N / 62 floor$$
  Each remainder indexes into the character set $\Sigma = 	ext{"0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"}$.
* **URL Safety Guarantee:** RFC 3986 defines unreserved characters that never require percent-encoding: alphanumerics `[a-zA-Z0-9]` plus `[-_.~]`. Base62 uses exclusively unreserved alphanumeric characters, preventing URL parsing corruption across email clients, SMS, and proxies.

### Q2: KGS Range Leasing & High-Throughput Token Generation
* **Coordination Protocol:**
  - etcd maintains a persistent key `/kgs/next_range_start = 50000000`.
  - When Worker $W_k$ boots or exhausts its current buffer, it executes an atomic `Compare-And-Swap` (CAS):
    $$	ext{Leased Range} = [R, R + 1\,000\,000 - 1], \quad 	ext{New Counter} = R + 1\,000\,000$$
* **Zero Locking Overhead:** During runtime, Worker $W_k$ increments an in-memory variable (`std::atomic<uint64_t>`). Generation latency is $< 10 	ext{ nanoseconds}$, yielding $100{,}000+$ keys/sec per worker node with zero inter-process locking or network overhead.

### Q3: HTTP Redirection Mechanics: 301 vs 302
* **HTTP 301 (Permanent Redirect):**
  - Response header: `Cache-Control: public, max-age=31536000`.
  - Browser writes the redirection mapping into its local disk cache SQLite database.
  - On next click, the browser navigates directly to the target URL without opening a TCP connection to `tinyurl.com`.
* **HTTP 302 (Found / Temporary):**
  - Response header: `Cache-Control: no-cache, no-store`.
  - Forces every click to hit the redirection service, enabling real-time analytics aggregation, geo-routing, A/B testing, and instant blocking of phishing domains.

### Q4: Mitigating Cache Penetration with Bloom Filters
* **Space Efficiency:** A Bloom filter with $N = 1 	ext{ Billion keys}$ and false positive probability $p = 0.001$ requires:
  $$M = -rac{N \ln p}{(\ln 2)^2} pprox 14.37 	ext{ Billion bits} pprox 1.71 	ext{ GB RAM}$$
* **RAM Execution:** The entire 1.71 GB Bloom filter resides comfortably in Redis RAM. Non-existent requests are terminated in $< 0.5 	ext{ ms}$, ensuring the backing database experiences zero IOPS load during high-volume random key scan attacks.

### Q5: Custom Alias Isolation & Race Conditions
* **Dual-Path Architecture:**
  - Standard generated URLs invoke KGS: guaranteed conflict-free, zero database uniqueness queries.
  - Custom vanity aliases follow a separate ACID path:
    ```sql
    INSERT INTO url_mappings (short_code, long_url, is_custom)
    VALUES ('blackfriday', 'https://store.com/sale', TRUE)
    ON CONFLICT (short_code) DO NOTHING;
    ```
* **Atomicity:** If 0 rows are affected, the service returns HTTP 409 Conflict ("Alias already taken"). Once successfully committed, the custom alias is appended to the Bloom filter.
