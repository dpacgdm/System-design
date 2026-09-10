# Design URL Shortener (TinyURL / Bitly) — Worked Answers

## Answer 1: Custom Alias Concurrency & Race Condition Prevention

To prevent two users from claiming the same custom alias concurrently across distributed pods:

1. **Unique Database Constraint**:
   The `short_code` column has a `PRIMARY KEY` or `UNIQUE` constraint in the database.
   
2. **Atomic Insert**:
   ```sql
   INSERT INTO urls (short_code, long_url, user_id, is_custom)
   VALUES ('blackfriday', 'https://store.com/deal', 'user-uuid', true)
   ON CONFLICT (short_code) DO NOTHING;
   ```
   If 0 rows are affected, the application immediately returns `HTTP 409 Conflict` ("Alias already taken").

3. **Distributed Lock (Optional for heavy write contention)**:
   Use Redis Redlock or a distributed lock on `lock:alias:blackfriday` with a 2-second TTL during creation.

---

## Answer 2: Base62 vs. Base64 in URL Contexts

Base64 uses `[0-9, a-z, A-Z, +, /]`:
1. **URL Encoding Issues**: In standard HTTP URLs, `+` is interpreted as a space in query parameters, and `/` is the path delimiter. Including them requires percent-encoding (`%2B`, `%2F`), expanding 7 characters to 9-11 characters and breaking link aesthetics.
2. **Base64URL Variant**: While Base64URL uses `-` and `_`, Base62 avoids all punctuation characters entirely, making it safe across SMS, email link parsers, QR codes, and command-line terminals.

---

## Answer 3: Phishing & Malware Defense Pipeline

1. **Synchronous Domain Blacklist (Bloom Filter)**:
   Maintain an in-memory Bloom filter of known phishing domains (Google Safe Browsing API, PhishTank). If the long URL matches, reject with HTTP 400 immediately.
   
2. **Asynchronous Sandbox Verification**:
   Publish new URL creations to Kafka `url_scan_queue`. A worker pool spins up headless Chrome in gVisor to inspect destination redirects, DOM elements, and SSL certificates. If malicious, flag `is_blocked = true` in the database and purge cache.
   
3. **Redirect Warning Page for New Accounts**:
   For unverified users or high-risk destination TLDs, render an intermediary warning landing page ("You are being redirected to...") to prevent drive-by download exploits.

---

## 4. Production Deep Dive: Singleflight Mutex Implementation

```go
package main

import (
	"context"
	"database/sql"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"
	"golang.org/x/sync/singleflight"
)

type URLRedirectService struct {
	rdb *redis.Client
	db  *sql.DB
	sf  singleflight.Group
}

func (s *URLRedirectService) ResolveURL(ctx context.Context, shortCode string) (string, error) {
	// 1. L1 Memory / Redis Lookup
	val, err := s.rdb.Get(ctx, "url:"+shortCode).Result()
	if err == nil {
		return val, nil
	}

	// 2. Cache Miss: Collapse concurrent DB reads using Singleflight
	res, err, _ := s.sf.Do(shortCode, func() (interface{}, error) {
		var longURL string
		err := s.db.QueryRowContext(ctx, 
			"SELECT long_url FROM urls WHERE short_code = $1 AND (expires_at IS NULL OR expires_at > NOW())", 
			shortCode,
		).Scan(&longURL)
		
		if err != nil {
			return "", err
		}

		// 3. Write-Through to Redis with 24-hour TTL
		_ = s.rdb.Set(ctx, "url:"+shortCode, longURL, 24*time.Hour).Err()
		return longURL, nil
	})

	if err != nil {
		return "", fmt.Errorf("URL not found or expired: %w", err)
	}

	return res.(string), nil
}
```
