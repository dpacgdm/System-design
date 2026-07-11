# Design Feature Store

---

## Learning Objectives

╔══════════════════════════════════════════════════════════════╗
║ AFTER THIS MODULE, YOU WILL BE ABLE TO:                      ║
╠══════════════════════════════════════════════════════════════╣
║ 1. Design online + offline feature stores with point-in-time ║
║ correctness and low-latency serving for inference.           ║
║ 2. Explain training-serving skew root causes and prevent     ║
║ them.                                                        ║
║ 3. Map Feast/Tecton patterns to AWS (DynamoDB, Redshift,     ║
║ SageMaker Feature Store, Kinesis, Glue).                     ║
║ 4. Diagnose feature freshness incidents, backfill gaps,      ║
║ and entity key mismatches in production.                     ║
║ 5. Choose materialization strategy: batch, stream,           ║
║ on-demand.                                                   ║
╚══════════════════════════════════════════════════════════════╝
---

## Wrong Mental Models (Destroy These First)

╔══════════════════════════════════════════════════════════════╗
║ #1: "Feature store = database for ML"                        ║
╠══════════════════════════════════════════════════════════════╣
║ WRONG. It is a consistency + serving contract between        ║
║ training and inference.                                      ║
╚══════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════╗
║ #2: "Online store mirrors offline exactly"                   ║
╠══════════════════════════════════════════════════════════════╣
║ WRONG. Different latency, compaction, and TTL constraints.   ║
╚══════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════╗
║ #3: "Join at request time is fine"                           ║
╠══════════════════════════════════════════════════════════════╣
║ WRONG. Join latency kills p99; pre-compute aggregations.     ║
╚══════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════╗
║ #4: "Same SQL for train and serve"                           ║
╠══════════════════════════════════════════════════════════════╣
║ WRONG. Training needs point-in-time; serving needs latest —  ║
║ different queries.                                           ║
╚══════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════╗
║ #5: "Backfill once and forget"                               ║
╠══════════════════════════════════════════════════════════════╣
║ WRONG. Schema drift and late data require continuous         ║
║ reconciliation.                                              ║
╚══════════════════════════════════════════════════════════════╝


---

## Core Teaching

### Foundation

> Staff / Principal stretch sections are marked below. Mastery gate: Staff required; Principal optional.

### 3.1 Why Feature Stores Exist

```
THE TRAINING-SERVING SKEW PROBLEM:

  Training (offline):
    Data scientist joins user_clickstream with user_demographics
    using "whatever values exist in the warehouse today."

  Serving (online):
    Model requests features for user_id=123 at inference time.
    Uses latest click count, latest embedding, etc.

  SKEW SCENARIOS:
    1. Training used future data (label leakage via timestamp bug)
    2. Training used batch aggregate computed differently than stream
    3. Training null-filled missing; serving defaults to 0
    4. Different code paths (Python pandas vs Java serving lib)

FEATURE STORE PROMISE:
  ONE DEFINITION of feature "user_7d_click_count" used in:
    - offline historical retrieval (point-in-time correct)
    - online low-latency lookup (latest materialized value)
    - monitoring (distribution drift vs training baseline)
```

### 3.2 Offline Store vs Online Store

```
OFFLINE STORE (training / batch scoring):

  Tech: S3 + Parquet, Redshift, Snowflake, BigQuery
  Access pattern: scan millions of rows, point-in-time joins
  Latency: seconds to hours
  Correctness: event_time <= observation_time (critical)

ONLINE STORE (real-time inference):

  Tech: DynamoDB, Redis, Cassandra, Feast Redis/Dynamo plugin
  Access pattern: GetFeatureValues(entity_keys) → <10ms p99
  Latency: 1-20ms
  Correctness: latest materialized value within freshness SLA

ARCHITECTURE:

  +-------------+     batch job      +---------------+
  | Raw events  | -----------------> | Offline store |
  | (Kinesis)   |                    | (S3/Redshift) |
  +------+------+                    +-------+-------+
         |                                   |
         | stream agg                        | historical retrieval
         v                                   v
  +-------------+     materialize     +---------------+
  | Stream      | ------------------> | Online store  |
  | processor   |                     | (DynamoDB)    |
  | (Flink)     |                     +-------+-------+
  +-------------+                             |
                                              v
                                       +-------------+
                                       | Model       |
                                       | serving     |
                                       +-------------+
```

### 3.3 Point-in-Time Correctness

```
Point-in-Time Correctness — section 1:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Point-in-Time Correctness — section 2:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Point-in-Time Correctness — section 3:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Point-in-Time Correctness — section 4:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Point-in-Time Correctness — section 5:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Point-in-Time Correctness — section 6:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Point-in-Time Correctness — section 7:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Point-in-Time Correctness — section 8:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Point-in-Time Correctness — section 9:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Point-in-Time Correctness — section 10:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```

### 3.4 Feature Definitions and Versioning

```
Feature Definitions and Versioning — section 1:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Feature Definitions and Versioning — section 2:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Feature Definitions and Versioning — section 3:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Feature Definitions and Versioning — section 4:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Feature Definitions and Versioning — section 5:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Feature Definitions and Versioning — section 6:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Feature Definitions and Versioning — section 7:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Feature Definitions and Versioning — section 8:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Feature Definitions and Versioning — section 9:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Feature Definitions and Versioning — section 10:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```

### 3.5 Materialization Jobs

```
Materialization Jobs — section 1:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Materialization Jobs — section 2:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Materialization Jobs — section 3:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Materialization Jobs — section 4:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Materialization Jobs — section 5:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Materialization Jobs — section 6:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Materialization Jobs — section 7:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Materialization Jobs — section 8:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Materialization Jobs — section 9:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Materialization Jobs — section 10:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```

### 3.6 Entity Keys and Feature Vectors

```
Entity Keys and Feature Vectors — section 1:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Entity Keys and Feature Vectors — section 2:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Entity Keys and Feature Vectors — section 3:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Entity Keys and Feature Vectors — section 4:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Entity Keys and Feature Vectors — section 5:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Entity Keys and Feature Vectors — section 6:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Entity Keys and Feature Vectors — section 7:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Entity Keys and Feature Vectors — section 8:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Entity Keys and Feature Vectors — section 9:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Entity Keys and Feature Vectors — section 10:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```

### 3.7 Feast Architecture Patterns

```
Feast Architecture Patterns — section 1:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Feast Architecture Patterns — section 2:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Feast Architecture Patterns — section 3:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Feast Architecture Patterns — section 4:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Feast Architecture Patterns — section 5:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Feast Architecture Patterns — section 6:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Feast Architecture Patterns — section 7:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Feast Architecture Patterns — section 8:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Feast Architecture Patterns — section 9:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Feast Architecture Patterns — section 10:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```

### 3.8 Tecton Enterprise Patterns

```
Tecton Enterprise Patterns — section 1:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Tecton Enterprise Patterns — section 2:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Tecton Enterprise Patterns — section 3:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Tecton Enterprise Patterns — section 4:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Tecton Enterprise Patterns — section 5:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Tecton Enterprise Patterns — section 6:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Tecton Enterprise Patterns — section 7:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Tecton Enterprise Patterns — section 8:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Tecton Enterprise Patterns — section 9:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Tecton Enterprise Patterns — section 10:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```

### 3.9 SageMaker Feature Store on AWS

```
SageMaker Feature Store on AWS — section 1:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
SageMaker Feature Store on AWS — section 2:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
SageMaker Feature Store on AWS — section 3:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
SageMaker Feature Store on AWS — section 4:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
SageMaker Feature Store on AWS — section 5:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
SageMaker Feature Store on AWS — section 6:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
SageMaker Feature Store on AWS — section 7:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
SageMaker Feature Store on AWS — section 8:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
SageMaker Feature Store on AWS — section 9:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
SageMaker Feature Store on AWS — section 10:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```

### 3.10 Stream Aggregations with Flink

```
Stream Aggregations with Flink — section 1:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Stream Aggregations with Flink — section 2:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Stream Aggregations with Flink — section 3:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Stream Aggregations with Flink — section 4:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Stream Aggregations with Flink — section 5:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Stream Aggregations with Flink — section 6:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Stream Aggregations with Flink — section 7:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Stream Aggregations with Flink — section 8:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Stream Aggregations with Flink — section 9:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Stream Aggregations with Flink — section 10:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```

### 3.11 Monitoring and Drift Detection

```
Monitoring and Drift Detection — section 1:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Monitoring and Drift Detection — section 2:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Monitoring and Drift Detection — section 3:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Monitoring and Drift Detection — section 4:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Monitoring and Drift Detection — section 5:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Monitoring and Drift Detection — section 6:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Monitoring and Drift Detection — section 7:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Monitoring and Drift Detection — section 8:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Monitoring and Drift Detection — section 9:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Monitoring and Drift Detection — section 10:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```

### 3.12 Backfill and Recovery

```
Backfill and Recovery — section 1:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Backfill and Recovery — section 2:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Backfill and Recovery — section 3:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Backfill and Recovery — section 4:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Backfill and Recovery — section 5:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Backfill and Recovery — section 6:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Backfill and Recovery — section 7:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Backfill and Recovery — section 8:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Backfill and Recovery — section 9:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```
```
Backfill and Recovery — section 10:

  Entity example: user_id (string), product_id (string)
  Feature: user_7d_purchase_sum (float64)
  event_time column: purchase_timestamp
  created_timestamp: when row landed in warehouse

  Point-in-time join SQL pattern (Redshift):
    SELECT entity_id, feature_value, event_time
    FROM feature_snapshots
    WHERE entity_id = :id
      AND event_time <= :as_of_timestamp
    ORDER BY event_time DESC
    LIMIT 1

  DynamoDB online schema:
    PK: FEATURE#user_7d_purchase_sum
    SK: ENTITY#user_id#12345
    value: 42.50
    updated_at: 2026-07-06T12:00:00Z
    version: 17

  Freshness SLA: 5 minutes (stream path)
  Alert: feature_staleness_seconds{feature} > 300
```

### 3.13 Training-Serving Skew Case Study 1

```
CASE 1: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 1:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.14 Training-Serving Skew Case Study 2

```
CASE 2: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 2:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.15 Training-Serving Skew Case Study 3

```
CASE 3: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 3:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.16 Training-Serving Skew Case Study 4

```
CASE 4: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 4:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.17 Training-Serving Skew Case Study 5

```
CASE 5: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 5:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.18 Training-Serving Skew Case Study 6

```
CASE 6: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 6:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.19 Training-Serving Skew Case Study 7

```
CASE 7: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 7:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.20 Training-Serving Skew Case Study 8

```
CASE 8: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 8:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.21 Training-Serving Skew Case Study 9

```
CASE 9: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 9:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.22 Training-Serving Skew Case Study 10

```
CASE 10: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 10:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.23 Training-Serving Skew Case Study 11

```
CASE 11: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 11:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.24 Training-Serving Skew Case Study 12

```
CASE 12: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 12:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.25 Training-Serving Skew Case Study 13

```
CASE 13: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 13:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.26 Training-Serving Skew Case Study 14

```
CASE 14: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 14:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.27 Training-Serving Skew Case Study 15

```
CASE 15: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 15:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.28 Training-Serving Skew Case Study 16

```
CASE 16: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 16:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.29 Training-Serving Skew Case Study 17

```
CASE 17: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 17:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.30 Training-Serving Skew Case Study 18

```
CASE 18: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 18:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.31 Training-Serving Skew Case Study 19

```
CASE 19: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 19:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.32 Training-Serving Skew Case Study 20

```
CASE 20: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 20:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.33 Training-Serving Skew Case Study 21

```
CASE 21: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 21:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.34 Training-Serving Skew Case Study 22

```
CASE 22: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 22:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.35 Training-Serving Skew Case Study 23

```
CASE 23: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 23:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.36 Training-Serving Skew Case Study 24

```
CASE 24: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 24:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.37 Training-Serving Skew Case Study 25

```
CASE 25: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 25:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.38 Training-Serving Skew Case Study 26

```
CASE 26: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 26:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.39 Training-Serving Skew Case Study 27

```
CASE 27: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 27:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.40 Training-Serving Skew Case Study 28

```
CASE 28: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 28:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

### 3.41 Training-Serving Skew Case Study 29

```
CASE 29: Skew root cause analysis

  Symptom: Offline AUC 0.91, online business metric flat.
  Investigation step 29:
    Compare feature distribution KS-test offline vs online log sample.
    Check materialization lag for top 20 features by importance.
    Verify entity key normalization (leading zeros, UUID case).

  Fix pattern:
    Register feature in Feast with identical transformation UDF
    compiled for Spark (offline) and Python (online push).
    Single git commit hash pinned in both pipelines.

  AWS: SageMaker Feature Store Record ingestion via PutRecord API
  vs batch CreateDataset from offline S3 export — verify parity job.
```

---

## Concrete Examples

### Uber Michelangelo

```
Layer 1 architecture notes for Uber Michelangelo.
```

```
Layer 2 architecture notes for Uber Michelangelo.
```

```
Layer 3 architecture notes for Uber Michelangelo.
```

```
Layer 4 architecture notes for Uber Michelangelo.
```

```
Layer 5 architecture notes for Uber Michelangelo.
```

```
Layer 6 architecture notes for Uber Michelangelo.
```

```
Layer 7 architecture notes for Uber Michelangelo.
```

```
Layer 8 architecture notes for Uber Michelangelo.
```

### Netflix feature platform

```
Layer 1 architecture notes for Netflix feature platform.
```

```
Layer 2 architecture notes for Netflix feature platform.
```

```
Layer 3 architecture notes for Netflix feature platform.
```

```
Layer 4 architecture notes for Netflix feature platform.
```

```
Layer 5 architecture notes for Netflix feature platform.
```

```
Layer 6 architecture notes for Netflix feature platform.
```

```
Layer 7 architecture notes for Netflix feature platform.
```

```
Layer 8 architecture notes for Netflix feature platform.
```

### Feast + DynamoDB on AWS

```
Layer 1 architecture notes for Feast + DynamoDB on AWS.
```

```
Layer 2 architecture notes for Feast + DynamoDB on AWS.
```

```
Layer 3 architecture notes for Feast + DynamoDB on AWS.
```

```
Layer 4 architecture notes for Feast + DynamoDB on AWS.
```

```
Layer 5 architecture notes for Feast + DynamoDB on AWS.
```

```
Layer 6 architecture notes for Feast + DynamoDB on AWS.
```

```
Layer 7 architecture notes for Feast + DynamoDB on AWS.
```

```
Layer 8 architecture notes for Feast + DynamoDB on AWS.
```

### Tecton managed

```
Layer 1 architecture notes for Tecton managed.
```

```
Layer 2 architecture notes for Tecton managed.
```

```
Layer 3 architecture notes for Tecton managed.
```

```
Layer 4 architecture notes for Tecton managed.
```

```
Layer 5 architecture notes for Tecton managed.
```

```
Layer 6 architecture notes for Tecton managed.
```

```
Layer 7 architecture notes for Tecton managed.
```

```
Layer 8 architecture notes for Tecton managed.
```

### Homegrown Redis + Spark

```
Layer 1 architecture notes for Homegrown Redis + Spark.
```

```
Layer 2 architecture notes for Homegrown Redis + Spark.
```

```
Layer 3 architecture notes for Homegrown Redis + Spark.
```

```
Layer 4 architecture notes for Homegrown Redis + Spark.
```

```
Layer 5 architecture notes for Homegrown Redis + Spark.
```

```
Layer 6 architecture notes for Homegrown Redis + Spark.
```

```
Layer 7 architecture notes for Homegrown Redis + Spark.
```

```
Layer 8 architecture notes for Homegrown Redis + Spark.
```


---

### Staff

## Production Patterns

### Single feature definition repo

```
Details...
```

### Single feature definition repo

```
Details...
```

### Single feature definition repo

```
Details...
```

### Single feature definition repo

```
Details...
```

### Scheduled + streaming materialization

```
Details...
```

### Scheduled + streaming materialization

```
Details...
```

### Scheduled + streaming materialization

```
Details...
```

### Scheduled + streaming materialization

```
Details...
```

### On-demand features via microservice

```
Details...
```

### On-demand features via microservice

```
Details...
```

### On-demand features via microservice

```
Details...
```

### On-demand features via microservice

```
Details...
```

### Feature validation gates in CI

```
Details...
```

### Feature validation gates in CI

```
Details...
```

### Feature validation gates in CI

```
Details...
```

### Feature validation gates in CI

```
Details...
```

### Shadow scoring parity checks

```
Details...
```

### Shadow scoring parity checks

```
Details...
```

### Shadow scoring parity checks

```
Details...
```

### Shadow scoring parity checks

```
Details...
```

### TTL and compaction on online store

```
Details...
```

### TTL and compaction on online store

```
Details...
```

### TTL and compaction on online store

```
Details...
```

### TTL and compaction on online store

```
Details...
```

### Changelog CDC from OLTP to features

```
Details...
```

### Changelog CDC from OLTP to features

```
Details...
```

### Changelog CDC from OLTP to features

```
Details...
```

### Changelog CDC from OLTP to features

```
Details...
```


---

## Failure Modes

### Stale features

```
Stale features failure mode deep dive.
```

### Stale features

```
Stale features failure mode deep dive.
```

### Stale features

```
Stale features failure mode deep dive.
```

### Stale features

```
Stale features failure mode deep dive.
```

### Stale features

```
Stale features failure mode deep dive.
```

### Stale features

```
Stale features failure mode deep dive.
```

### Missing entity keys

```
Missing entity keys failure mode deep dive.
```

### Missing entity keys

```
Missing entity keys failure mode deep dive.
```

### Missing entity keys

```
Missing entity keys failure mode deep dive.
```

### Missing entity keys

```
Missing entity keys failure mode deep dive.
```

### Missing entity keys

```
Missing entity keys failure mode deep dive.
```

### Missing entity keys

```
Missing entity keys failure mode deep dive.
```

### Backfill overwrote online

```
Backfill overwrote online failure mode deep dive.
```

### Backfill overwrote online

```
Backfill overwrote online failure mode deep dive.
```

### Backfill overwrote online

```
Backfill overwrote online failure mode deep dive.
```

### Backfill overwrote online

```
Backfill overwrote online failure mode deep dive.
```

### Backfill overwrote online

```
Backfill overwrote online failure mode deep dive.
```

### Backfill overwrote online

```
Backfill overwrote online failure mode deep dive.
```

### Schema migration without version bump

```
Schema migration without version bump failure mode deep dive.
```

### Schema migration without version bump

```
Schema migration without version bump failure mode deep dive.
```

### Schema migration without version bump

```
Schema migration without version bump failure mode deep dive.
```

### Schema migration without version bump

```
Schema migration without version bump failure mode deep dive.
```

### Schema migration without version bump

```
Schema migration without version bump failure mode deep dive.
```

### Schema migration without version bump

```
Schema migration without version bump failure mode deep dive.
```

### Clock skew in event_time

```
Clock skew in event_time failure mode deep dive.
```

### Clock skew in event_time

```
Clock skew in event_time failure mode deep dive.
```

### Clock skew in event_time

```
Clock skew in event_time failure mode deep dive.
```

### Clock skew in event_time

```
Clock skew in event_time failure mode deep dive.
```

### Clock skew in event_time

```
Clock skew in event_time failure mode deep dive.
```

### Clock skew in event_time

```
Clock skew in event_time failure mode deep dive.
```

### Duplicate entity IDs

```
Duplicate entity IDs failure mode deep dive.
```

### Duplicate entity IDs

```
Duplicate entity IDs failure mode deep dive.
```

### Duplicate entity IDs

```
Duplicate entity IDs failure mode deep dive.
```

### Duplicate entity IDs

```
Duplicate entity IDs failure mode deep dive.
```

### Duplicate entity IDs

```
Duplicate entity IDs failure mode deep dive.
```

### Duplicate entity IDs

```
Duplicate entity IDs failure mode deep dive.
```

### Hot key in DynamoDB

```
Hot key in DynamoDB failure mode deep dive.
```

### Hot key in DynamoDB

```
Hot key in DynamoDB failure mode deep dive.
```

### Hot key in DynamoDB

```
Hot key in DynamoDB failure mode deep dive.
```

### Hot key in DynamoDB

```
Hot key in DynamoDB failure mode deep dive.
```

### Hot key in DynamoDB

```
Hot key in DynamoDB failure mode deep dive.
```

### Hot key in DynamoDB

```
Hot key in DynamoDB failure mode deep dive.
```


---

## SRE Diagnostic Toolkit

```
# Feast feature freshness
feast materialize-incremental --end-date $(date -u +%Y-%m-%dT%H:%M:%S)

# DynamoDB point read latency
aws dynamodb get-item --table-name online_features \
  --key '{"PK":{"S":"FEATURE#user_7d_click"},"SK":{"S":"ENTITY#user#123"}}'

# Compare offline vs online for entity sample
python scripts/feature_parity_check.py --entity-id 123 --feature user_7d_click

# Redshift point-in-time query
SELECT * FROM feature_log WHERE entity_id='123' AND event_time <= '2026-07-01' ORDER BY event_time DESC LIMIT 1;

# CloudWatch alarm
feature_materialization_lag_seconds > 600

# Kinesis iterator age (stream path)
GetRecords.IteratorAgeMilliseconds
```

# Diagnostic 1: sample online/offline parity for canary entities

# Diagnostic 2: sample online/offline parity for canary entities

# Diagnostic 3: sample online/offline parity for canary entities

# Diagnostic 4: sample online/offline parity for canary entities

# Diagnostic 5: sample online/offline parity for canary entities

# Diagnostic 6: sample online/offline parity for canary entities

# Diagnostic 7: sample online/offline parity for canary entities

# Diagnostic 8: sample online/offline parity for canary entities

# Diagnostic 9: sample online/offline parity for canary entities

# Diagnostic 10: sample online/offline parity for canary entities

# Diagnostic 11: sample online/offline parity for canary entities

# Diagnostic 12: sample online/offline parity for canary entities

# Diagnostic 13: sample online/offline parity for canary entities

# Diagnostic 14: sample online/offline parity for canary entities

# Diagnostic 15: sample online/offline parity for canary entities

# Diagnostic 16: sample online/offline parity for canary entities

# Diagnostic 17: sample online/offline parity for canary entities

# Diagnostic 18: sample online/offline parity for canary entities

# Diagnostic 19: sample online/offline parity for canary entities

# Diagnostic 20: sample online/offline parity for canary entities

# Diagnostic 21: sample online/offline parity for canary entities

# Diagnostic 22: sample online/offline parity for canary entities

# Diagnostic 23: sample online/offline parity for canary entities

# Diagnostic 24: sample online/offline parity for canary entities

# Diagnostic 25: sample online/offline parity for canary entities

# Diagnostic 26: sample online/offline parity for canary entities

# Diagnostic 27: sample online/offline parity for canary entities

# Diagnostic 28: sample online/offline parity for canary entities

# Diagnostic 29: sample online/offline parity for canary entities

# Diagnostic 30: sample online/offline parity for canary entities

---

## Decision Framework


| Scenario | Offline | Online | Tooling |
|----------|---------|--------|---------|
| Batch ML weekly | S3 Parquet | None until deploy | Glue + SageMaker |
| Real-time fraud | Redshift history | DynamoDB | Feast + Flink |
| Enterprise governance | Lakehouse | Redis cluster | Tecton |
| Startup MVP | Postgres exports | Redis | Feast local |

```
MATERIALIZATION CHOICE:

  Batch only (hourly Glue job) → OK if 1hr staleness acceptable
  Stream (Flink) → fraud, recommendations
  On-demand (call microservice) → rare features, heavy compute
```

---

## Incident Scenario: Feature Freshness Degradation

```
P2: Recommendation CTR dropped 12%. Model unchanged.
Feature freshness dashboard: user_7d_click 45 min stale (SLA 5 min).
Flink job checkpoint failing. DynamoDB write throttle on hot partition.
```

---



---

> **Answer key (do not open until you attempt the Ops Sim / questions):**
> [`../answers/Week-14-Collaboration-and-AI-Designs/Design Feature Store Answers.md`](../answers/Week-14-Collaboration-and-AI-Designs/Design Feature Store Answers.md)

## Key Takeaways

╔══════════════════════════════════════════════════════════════╗
║ REMEMBER:                                                    ║
╠══════════════════════════════════════════════════════════════╣
║ 1. Feature store = contract eliminating training-serving     ║
║ skew.                                                        ║
║ 2. Offline needs point-in-time; online needs fresh + fast.   ║
║ 3. One feature definition, two materialization paths.        ║
║ 4. Monitor freshness, null rate, and distribution drift.     ║
║ 5. Entity key normalization bugs cause silent missing        ║
║ features.                                                    ║
╚══════════════════════════════════════════════════════════════╝
---

## Targeted Reading

```
Feast documentation — Point-in-Time Joins
Tecton blog: Declarative transformations
AWS SageMaker Feature Store developer guide Ch 1-4
Chapman et al., "Machine Learning Systems" — feature engineering chapter
Sculley et al., "Hidden Technical Debt in ML" (training-serving skew)
```
```

---

### Principal stretch

## Design Gates (mandatory)

Answer these before calling the design complete. Keep responses concise in the
learner notes; compare against the answer key only after attempting the gates.

> Gate template: [`../templates/DESIGN_MODULE_GATES.md`](../templates/DESIGN_MODULE_GATES.md)
> Model responses: [`../answers/Week-14-Collaboration-and-AI-Designs/Design Feature Store Answers.md`](../answers/Week-14-Collaboration-and-AI-Designs/Design%20Feature%20Store%20Answers.md)

### Gate 1 - Authn/z trust boundary

1. Who is authenticated in this design: end user, admin, service, device, worker, tenant, or partner?
2. Where does the first untrusted request cross into your trusted control plane?
3. Which component makes the final authorization decision for each protected object or action?
4. What identity artifact is accepted: session cookie, bearer token, API key, mTLS SPIFFE ID, signed URL, or job identity?
5. What does the system do when the identity provider, policy store, or trust bundle is unavailable?

### Gate 2 - Abuse and misuse

6. Which actor can generate the largest write amplification or fan-out?
7. Which endpoint or background job can be abused while still authenticated?
8. What per-user, per-tenant, per-key, per-IP, per-region, and global quotas are required?
9. What telemetry distinguishes a legitimate flash crowd from abuse or scraping?
10. Which retry policy could amplify a partial outage into a full outage?

### Gate 3 - Multi-tenant isolation, if multi-tenant

11. What is the tenancy model for API, database, cache, queue/topic, search/index, and object storage?
12. Where is tenant context required, and how is it propagated through async jobs and support tools?
13. Which shared resource has reserved capacity or fair-share limits per tenant or tier?
14. How can one tenant be throttled, disabled, migrated, or isolated without affecting others?
15. What test proves a tenant cannot read another tenant's data through cache, search, export, or logs?

### Gate 4 - Unit cost at target scale

16. What is the business unit for cost: request, message, ride, order, document, query, minute, or tenant?
17. At the stated target scale and peak multiplier, what is the rough unit cost?
18. Which line items dominate: compute, storage, replication, egress, NAT, observability, ML inference, third-party APIs, or idle headroom?
19. What cost metric pages before margin, budget, or SLO error budget is breached?
20. What graceful degradation lowers cost without damaging the correctness-critical path?

### Gate 5 - Failure blast radius

21. What is the smallest unit that can fail independently: partition, shard, cell, topic, region, tenant, cache key, model, worker pool, or queue?
22. Which dependencies are shared between critical and non-critical paths?
23. What fails closed, what serves stale, and what can be disabled first?
24. Which runbook action could accidentally widen blast radius?
25. What game day proves the blast radius stays inside the intended boundary?
