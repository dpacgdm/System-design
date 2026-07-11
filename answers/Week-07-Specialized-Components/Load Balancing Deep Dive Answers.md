# Answer Key — Load Balancing Deep Dive

> Open only after attempting the learner file questions.

## Expert Analysis

### Question 1: Causal Chain

```
CAUSAL CHAIN
━━━━━━━━━━━━

ROOT CAUSE A — gRPC L4 BLACK HOLE (architectural):
  order-service exposed via NLB (L4), not ALB gRPC.
  checkout-api and other callers use single long-lived HTTP/2 connection
  to NLB IP → NLB flow hash pins connection → order-pod-7 receives
  ~85% of all gRPC RPCs across 8 pods.
  This predates the incident but was masked until load increased (Prime Day).

ROOT CAUSE B — KEEPALIVE CHANGE (trigger):
  v3.2.0 increased keepalive_time_ms 30s → 300s (5 min).
  Connections rebalance only on reconnect.
  Under Prime Day load, pod-7 already saturated; longer connection lifetime
  PREVENTS natural churn that previously masked skew (30s forced more redistribution).

AMPLIFYING FACTOR C — POD-7 SATURATION:
  pod-7: 4,812 active streams, GC pause 2.8s, CPU 98%
  CreateOrder RPCs timeout at 3s (client deadline)
  checkout-api returns 502/504 to users

DOWNSTREAM EFFECT D — HEALTH CHECK FLAPPING:
  /health/ready includes order-service gRPC probe with 3s timeout
  When pod-7 saturated, gRPC health check times out
  8 checkout-api tasks fail ready check → ALB marks UNHEALTHY
  Traffic concentrates on remaining 22 tasks → more load → more timeouts
  Flapping: unhealthy → less traffic → recover → healthy → overload → repeat

SYMPTOM E — WEBSOCKET DROPS (partially independent):
  tg-checkout-ws NOT deployed at 13:50
  BUT checkout-api deploy at 13:50 changed ALB target pool composition
  Shared ALB? NO — separate target groups, same ALB listeners possible.

  Actual mechanism:
    checkout-api deploy replaced 30 tasks over 10 minutes
    ALB cross-zone rebalancing shifted flow hash temporarily
    WS connections on checkout-api tasks: NONE (WS is separate TG)
  
  Re-read architecture: tg-checkout-ws separate — drops at 13:52 correlate with:
    → Shared Redis pub/sub channel overload from order timeout retries
    → OR ALB idle timeout on ws TG during task recycle (ws TG also deployed?)
    → Incident notes: ws drops coincide with checkout-api deploy

  Most likely ws cause:
    checkout-api deploy triggered HPA scale on shared cluster capacity
    ws tasks CPU stolen → heartbeat lag → ALB idle timeout 60s on ws TG
    (ws idle_timeout not raised — default 60s)
    Secondary: client order-status polls fallback overloaded checkout-api

SHARED ROOT: pod-7 saturation (A+B+C) drives D and indirectly E.

INDEPENDENT: EU latency worse — Route 53 sends to us-east for GA bypass users;
  not caused by gRPC skew but amplifies timeout rate.
```

### Question 2: Immediate Mitigation (15 Minutes)

```
14:08–14:23 ACTIONS (exact order):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. ROLLBACK order-service keepalive (14:09) — fastest redistribution trigger:
   aws ecs update-service \
     --cluster order-prod \
     --service order-service \
     --task-definition order-service:318 \
     --force-new-deployment
   # Revision 318 = v3.1.9 with keepalive_time_ms=30000

2. SCALE order-service horizontally (14:10) — partial relief on pod-7:
   aws application-autoscaling register-scalable-target \
     --service-namespace ecs --resource-id service/order-prod/order-service \
     --scalable-dimension ecs:service:DesiredCount \
     --min-capacity 8 --max-capacity 16
   aws application-autoscaling put-scaling-policy ... 
   # Or manual: desired count 8 → 14 immediately

3. CIRCUIT BREAKER on checkout-api → order-service (14:11):
   # AppConfig / feature flag:
   order_grpc_circuit_open: true
   fail_fast_timeout_ms: 500
   # Return 503 "checkout temporarily unavailable" — NOT 30s spinner
   # Stops thread pool exhaustion on checkout-api

4. DECOUPLE health check from order-service (14:12) — stop flapping:
   # Emergency: point ALB health check to /health/live only
   aws elbv2 modify-target-group \
     --target-group-arn $TG_CHECKOUT_API \
     --health-check-path /health/live \
     --health-check-timeout-seconds 2
   # Tradeoff: unhealthy checkout tasks may stay in rotation
   # Acceptable for 15 min vs total pool removal

5. DO NOT disable stickiness during incident (14:13):
   # Would redistribute sessions AND worsen hot spot debugging
   # Stickiness not the primary cause today

6. DO NOT restart NLB (14:14):
   # No effect on connection pinning; wastes bridge time

7. VERIFY pod-7 drain (14:15):
   kubectl cordon order-pod-7  # or ECS stop task with replacement
   # Forces client reconnect → redistributes gRPC load
   aws ecs stop-task --cluster order-prod --task $POD7_TASK_ARN \
     --reason "incident-redirect-grpc-load"

8. WEBSOCKET idle timeout (14:18) — prevent further ws drops:
   aws elbv2 modify-load-balancer-attributes \
     --load-balancer-arn $ALB_ARN \
     --attributes Key=idle_timeout.timeout_seconds,Value=3600

WILL NOT DO:
  ✗ Scale checkout-api without fixing order-service (amplifies gRPC load)
  ✗ Increase gRPC deadline beyond 3s (worse UX, thread hoarding)
  ✗ Enable NLB cross-zone (wrong problem, adds cost)
```

### Question 3: order-service Load Distribution Fix

```
OPTION COMPARISON
━━━━━━━━━━━━━━━━━

┌────────────────────┬──────────────┬───────────────┬──────────────────┐
│ Approach           │ Pros         │ Cons          │ ShopStream fit   │
├────────────────────┼──────────────┼───────────────┼──────────────────┤
│ ALB gRPC TG        │ Central LB,  │ Extra hop,    │ GOOD — already   │
│                    │ stream-level │ LCU cost      │ uses ALB at edge │
│                    │ distribution │               │                  │
├────────────────────┼──────────────┼───────────────┼──────────────────┤
│ Client-side RR     │ No L7 LB,    │ Every client  │ GOOD — few       │
│ (gRPC resolver)    │ direct pods  │ must implement│ internal callers │
├────────────────────┼──────────────┼───────────────┼──────────────────┤
│ max_connection_age │ Minimal code │ Band-aid,     │ BAD — primary    │
│ on server only     │ change       │ uneven bursts │ fix insufficient │
└────────────────────┴──────────────┴───────────────┴──────────────────┘

RECOMMENDATION: ALB gRPC target group for external-ish boundary
                + client-side round_robin for service-mesh internal

IMPLEMENTATION (Terraform — internal ALB gRPC target group):

  resource "aws_lb" "order_internal" {
    name               = "order-grpc-alb"
    internal           = true
    load_balancer_type = "application"
    subnets            = var.private_subnet_ids
    security_groups    = [aws_security_group.order_alb.id]
  }

  resource "aws_lb_target_group" "order_grpc" {
    name             = "order-grpc"
    port             = 50051
    protocol         = "HTTPS"
    protocol_version = "GRPC"
    vpc_id           = var.vpc_id
    target_type      = "ip"

    health_check {
      protocol            = "HTTP"
      path                = "/grpc.health.v1.Health/Check"
      matcher             = "0-99"
      interval            = 10
      healthy_threshold   = 2
      unhealthy_threshold = 2
    }
  }

checkout-api gRPC channel config:

  order_service:
    address: order-grpc-alb.internal:443
    tls: true
    # Single ALB DNS — ALB distributes streams across pods
    # Do NOT use pick_first with one address expecting K8s-style RR

Keep server max_connection_age=300s as SECONDARY safety valve:

  keepaliveParams := keepalive.ServerParameters{
    MaxConnectionAge:      5 * time.Minute,
    MaxConnectionAgeGrace: 30 * time.Second,
  }

Migrate path:
  1. Deploy ALB gRPC TG parallel to NLB
  2. Canary 10% checkout-api callers to ALB endpoint
  3. Monitor RequestCountPerTarget skew < 1.5:1
  4. Cutover 100%, decommission NLB after 48h
```

### Question 4: Health Check and Deploy Hardening

```
PRINCIPLE: /health/ready must not depend on degraded optional dependencies
           during incident; circuit breaker OPEN should not fail liveness.

HEALTH CHECK TIERS:

  /health/live  → process up, thread pool not exhausted
                  ALB health check points HERE (always)

  /health/ready → Redis, RDS, order-service gRPC
                  Used by ECS deployment circuit, NOT ALB

HEALTH ENDPOINTS (Python/FastAPI example):

  @app.get("/health/live")   # ALB target — liveness only
  def live():
      if thread_pool.queue_size > 500:
          return 503  # backpressure — fail liveness
      return 200

  @app.get("/health/ready")  # ECS deploy gate — not ALB
  def ready():
      if circuit_breaker.order_grpc.state == OPEN:
          return 200  # HTTP layer ready; degrade checkout feature
      return check_all_dependencies()

CIRCUIT BREAKER (Week 6 tie-in):
  order-service failures → breaker OPEN → checkout fast-fails CreateOrder
  HTTP layer stays healthy; checkout returns 503 with retry-after

DEPLOY ORDERING:
  1. Deploy downstream (order-service) FIRST, validate gRPC skew metrics
  2. Deploy upstream (checkout-api) SECOND
  3. Block pipeline if RequestCountPerTarget max/min > 3:1

TARGET GROUP HARDENING (Terraform):

  health_check {
    path                = "/health/live"
    interval            = 10
    unhealthy_threshold = 3
    timeout             = 3
  }

  slow_start {
    duration_seconds = 60
  }

ALERT (new):
  Metric: order_grpc_request_skew_ratio =
    max(rate by pod) / min(rate by pod)
  Threshold: > 3 for 5 min → P2 page (black hole detector)
```

### Question 5: WebSocket Reconnect Storm

```
WHY WS DROPPED (root cause for tg-checkout-ws):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. ALB idle_timeout = 60s on listener (default)
  2. checkout-api incident caused Redis pub/sub delay (order events backlog)
  3. ws gateway tasks blocked on Redis publish → missed application-level
     ping → client idle but ALB sees 60s without data → ALB closes TCP
  4. 8,400 connections dropped over 3 minutes
  5. Clients reconnect immediately (no jitter) → 2,200/sec thundering herd

  Correlation with checkout-api deploy: deploy caused CPU contention on
  shared Fargate capacity pool + Redis load from retries — not direct TG overlap.

FIXES:

ALB:
  idle_timeout.timeout_seconds = 3600

ECS:
  Separate capacity provider for ws gateway (no shared CPU steal)
  preStop hook on ws tasks:
    #!/bin/bash
    curl -X POST localhost:8080/admin/drain
    sleep 90

  deregistration_delay = 300 on tg-checkout-ws

APPLICATION (Week 1):
  Server: ping every 30s (well under ALB idle timeout)
  Client reconnect with jitter:
    delay = min(30000, 1000 * 2^attempt) + random(0, 1000) ms
    setTimeout(connect, delay)

DEPLOY:
  Deploy ws gateway during low-traffic window OR
  blue/green with connection drain gate:
    - Wait for websocket_active_connections < 100 on draining tasks
    - Before terminating

METRIC ALERT:
  ws_reconnect_rate > 500/sec for 2 min during deploy → auto-rollback
```

---

## Ops Sim: Northstar gRPC Pool Hotspot

### Q1 - Layer & root cause

HTTP/2 multiplexing over an L4 load balancer pinned too much traffic to one backend connection and pod.

A strong answer separates the trigger from retry, cache, routing, or observability amplifiers and states the invariant that cannot be violated.

### Q2/Q3 - Evidence

- `pricing_p99_ms: 95 -> 1800`
- `backend_cpu_pod_7: 99%; fleet_median=34%`
- `grpc_active_streams pod_7=8200; others <500`
- `nlb_new_connections_per_sec: flat`
- `envoy_outlier_ejections: 0`
- `client: channel_pool_size=1 target=pricing-nlb`
- `pricing-pod-7: queue depth 6400`
- `envoy: no outlier ejection configured`
- Config clue: `channel_pool_size: 1`
- Config clue: `max_concurrent_streams: unlimited`

### Q4 - Red herrings

Do not trust fleet averages, shallow health checks, or resource alerts that are not tied to the affected user slice. Downstream lag and retries may be symptoms to control, but they do not automatically identify the first cause.

### Q5/Q6 - Safe first 15 minutes

1. Declare severity, name the invariant, and assign subsystem owners.
2. Freeze new deploys, rollouts, rebalances, schema changes, or bulk replays touching the path.
3. Stop the active amplifier called out in the config/timeline.
4. Shed or degrade noncritical work before weakening checkout, payment, inventory, or tenant isolation.
5. Verify with the primary SLI, the scarce-resource metric, and the lag/error derivative.
6. Start an affected-record ledger for repair before any manual replay.

### Q7 - Bad fixes

- `scale pods only`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `raise max concurrent streams`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `retry same subchannel`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `trust shallow health checks`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.

### Q8 - Capacity / blast radius

Quantify current usage, safe ceiling, growth rate, and time-to-exhaustion for queue/lag, connection or thread pools, disk/WAL/compaction, and affected business records. Scaling is only safe if the downstream dependency has headroom.

### Q9 - Correctness invariant

Accepted orders, money movement, inventory reservations, tenant isolation, and source-of-truth state must remain conservative. If the outcome is uncertain, mark it uncertain and reconcile instead of guessing.

### Q10 - Data repair

Use source-of-truth rows, stable idempotency keys, LSNs/offsets, and the incident window to define the repair set. Replay with duplicate suppression, throttle to downstream headroom, and record customer-visible corrections.

### Q11 - Durable fixes

- multiple gRPC channels.
- L7 load balancing or xDS.
- latency/status outlier detection.
- health checks with queue saturation.

Acceptance criteria: the old failure is reproduced in a drill, the new guardrail pages before customer impact, and the unsafe configuration cannot be enabled without review.

### Q12/Q13 - Alerting and runbook

Page on SLO burn, correctness failures, lag derivative, and scarce-resource exhaustion in the affected slice. By T+10 include incident commander, service owner, data/platform owner, product/business owner, support, and security/payments if trust or money is involved. Pre-authorized: stop unsafe rollouts, shed noncritical work, conservative fallback. Senior approval: durability downgrade, destructive repair, broad failover, or accepting derived data as truth.

---
