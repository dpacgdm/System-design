# Answer Key — Design Google Docs

> Open only after attempting the learner file questions.

## Expert Analysis

### Q1: Most Likely Bug Class

```
Transform optimization likely skipped edge case in concurrent
insert+delete at same offset (classic OT pitfall).

Evidence:
  - Single doc_id dominating errors → deterministic repro
  - revision_gap_fetch spike → clients detecting revision mismatch
  - Text "reverting" → server acked transformed op client couldn't apply

The optimization probably memoized transform results by op TYPE pair
(insert, delete) without including context (offset overlap class).
```

### Q2: Worked Answer

```
ANSWER Q2:

  Priority 2: Rollback deploy first
  Enable read-only mode flag for hot doc_ids
  
  
  

  Detailed steps:
    1. Query CloudWatch Logs Insights for transform_failed grouped by doc_id
    2. Export op log segment from S3 for affected revision range
    3. Offline replay with golden transform → compute canonical checksum
    4. Push snapshot repair event; force client hard refresh via WS control msg
    5. Post-incident: add transform pair coverage matrix (47 pairwise cases)

  AWS commands:
    aws ecs update-service --cluster collab --service collab-svc \
      --task-definition collab:213  # previous good revision

    aws s3 cp s3://docs-ops/d_hot/segment_4820_4900.ops.gz ./replay/
```

### Q3: Worked Answer

```
ANSWER Q3:

  Priority 3: Isolate affected doc_ids via log query
  
  Run checksum bot against top 1000 active docs
  
  

  Detailed steps:
    1. Query CloudWatch Logs Insights for transform_failed grouped by doc_id
    2. Export op log segment from S3 for affected revision range
    3. Offline replay with golden transform → compute canonical checksum
    4. Push snapshot repair event; force client hard refresh via WS control msg
    5. Post-incident: add transform pair coverage matrix (47 pairwise cases)

  AWS commands:
    aws ecs update-service --cluster collab --service collab-svc \
      --task-definition collab:213  # previous good revision

    aws s3 cp s3://docs-ops/d_hot/segment_4820_4900.ops.gz ./replay/
```

### Q4: Worked Answer

```
ANSWER Q4:

  Priority 4: Isolate affected doc_ids via log query
  
  
  Replay ops from immutable log with v2.13.0 transform library
  

  Detailed steps:
    1. Query CloudWatch Logs Insights for transform_failed grouped by doc_id
    2. Export op log segment from S3 for affected revision range
    3. Offline replay with golden transform → compute canonical checksum
    4. Push snapshot repair event; force client hard refresh via WS control msg
    5. Post-incident: add transform pair coverage matrix (47 pairwise cases)

  AWS commands:
    aws ecs update-service --cluster collab --service collab-svc \
      --task-definition collab:213  # previous good revision

    aws s3 cp s3://docs-ops/d_hot/segment_4820_4900.ops.gz ./replay/
```

### Q5: Worked Answer

```
ANSWER Q5:

  Priority 5: Isolate affected doc_ids via log query
  
  
  
  Mandatory 1M-op property test in CI + 24h canary at 1% traffic

  Detailed steps:
    1. Query CloudWatch Logs Insights for transform_failed grouped by doc_id
    2. Export op log segment from S3 for affected revision range
    3. Offline replay with golden transform → compute canonical checksum
    4. Push snapshot repair event; force client hard refresh via WS control msg
    5. Post-incident: add transform pair coverage matrix (47 pairwise cases)

  AWS commands:
    aws ecs update-service --cluster collab --service collab-svc \
      --task-definition collab:213  # previous good revision

    aws s3 cp s3://docs-ops/d_hot/segment_4820_4900.ops.gz ./replay/
```

---
