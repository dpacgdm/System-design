# Answer Key — Design Uber

> Open only after attempting the learner file questions.

## Expert Analysis
### Q1-Q4 Worked Answers

```
ROOT CAUSE: Location processor bug with TTL=300s kept stale entries.
Drivers moved but old positions persisted. GEO index bloated with
ghost entries at wrong coordinates → GEORADIUS returned drivers
outside real range OR index too large → Redis CPU saturated →
queries timed out → 0 candidates returned.

MITIGATION:
  1. Rollback TTL to 30s
  2. FLUSHDB on geo index + rebuild from Kafka last 60s (5 min)
  3. Enable matching fallback: 2x radius with haversine pre-filter
  4. Manual surge reset API for SF metro

ONLINE vs CANDIDATES: status=ONLINE in driver service but geo index
  had stale coords — split-brain between status DB and Redis geo.

FIXES: Single source of truth for availability (geo index IS truth);
  atomic update status+location; Redis CPU autoscaling; load test NYE.
```


---
