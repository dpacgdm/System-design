# Retention Test - SD Gaps

Questions only. Covers the interview SD gap modules: Service Discovery, Trending Hashtags, Ad Platform, Ticketmaster, Google Flights, Recommendation System, and Agentic Workflow Platform, plus spaced mix from related weeks.
Attempt without opening answers.

## Rules

```text
1. Answer from memory; do not open modules or answer keys.
2. Rapid-fire answers should name mechanism, evidence, invariant, and one bad fix.
3. Compound scenarios should be answered like you are incident lead.
4. If unsure, choose the safest invariant-preserving action and move on.
```

---

## Part 1: Rapid-fire spaced review

**Q01 [SD]**
A Java client keeps calling an old service IP after DNS failover. What cache behavior do you inspect?

**Q02 [SD]**
Client-side discovery continues serving while the registry is down. What bounded stale-cache policy makes that safe?

**Q03 [SD]**
A registry outage causes full catalog polls to jump 200x. What client behavior amplified the trigger?

**Q04 [SD]**
Readiness is green while DB pools are exhausted. Which health-check distinction was missed?

**Q05 [SD]**
Zone-aware routing sends all az-b traffic to az-a. Which capacity check is required before spillover?

**Q06 [SD]**
Endpoint cache TTL is shortened from 60s to 2s during a registry brownout. Why can this worsen availability?

**Q07 [SD]**
A Kubernetes Service routes to terminating pods. Which objects and drain metrics do you inspect?

**Q08 [SD]**
Consul/etcd watches compact and clients reconnect. What metric separates watch lag from backend failure?

**Q09 [W1 DNS]**
Why is Route 53 failover not enough if clients keep persistent HTTP connections?

**Q10 [W6 Retries]**
A discovery refresh fails and all clients retry every second. Which retry pattern is required?

**Q11 [W7 LB]**
How does service discovery differ from load balancing, and where do they overlap?

**Q12 [W8 Obs]**
Which discovery metrics should page before user-visible 5xx?

**Q13 [REC]**
Why can a ranker not recover items that candidate generation failed to retrieve?

**Q14 [REC]**
Global CTR improves while conversion falls. What guardrail interpretation should stop rollout?

**Q15 [REC]**
Name five candidate generation sources and one risk for each.

**Q16 [REC]**
What does the online Feature Store provide to a recommender at serving time?

**Q17 [REC]**
What is training-serving skew in a recommendation system?

**Q18 [REC]**
A cache key is `surface:item_id` in a multi-tenant catalog. What invariant is missing?

**Q19 [REC]**
A new seller's click velocity rises 900% from two ASNs. What abuse checks distinguish fraud from organic trend?

**Q20 [REC]**
Why is rankTopK a cost and latency control, not only a quality knob?

**Q21 [REC]**
How should cold start differ for users, items, tenants, and regions?

**Q22 [REC]**
What logs are required for unbiased recommendation training?

**Q23 [W14 Feature Store]**
Which freshness and null-rate checks connect feature store incidents to recommender quality?

**Q24 [W12 Search]**
How is recommendation ranking different from search ranking?

**Q25 [AGENT]**
Why is an agentic workflow platform distinct from an LLM serving platform?

**Q26 [AGENT]**
What should the orchestrator enforce that the planner must not control?

**Q27 [AGENT]**
A tool retry uses a random UUID idempotency key. Why can that duplicate side effects?

**Q28 [AGENT]**
Tool output contains instructions to ignore policy. What classification should the platform assign to tool output?

**Q29 [AGENT]**
What metadata must every memory item carry to avoid stale or cross-tenant harm?

**Q30 [AGENT]**
Which actions require human approval in an agent platform?

**Q31 [AGENT]**
Why should approval timeout fail closed for high-risk actions?

**Q32 [AGENT]**
What eval suites are missing if only prompt golden tests run?

**Q33 [AGENT]**
What blast-radius boundary should exist for a new CRM connector rollout?

**Q34 [W6 Saga]**
How do saga idempotency keys apply to tool-calling agents?

**Q35 [08b Auth]**
Which delegated auth checks apply before an agent calls a tool?

**Q36 [W8 Obs]**
Which metrics distinguish a planner loop from model-serving latency?

---

## Part 2: Compound Scenario A - Discovery Control Plane

Northstar checkout clients use client-side service discovery.
A registry leader stall lasts 20 seconds, then all clients poll full catalogs every 5 seconds with no jitter.
az-c inventory readiness flaps because a local dependency pool is exhausted.

```text
checkout 5xx:                  0.2% -> 6.4%
registry p99:                  40 ms -> 5.2 s
full catalog polls:            2k/min -> 310k/min
endpoint cache age p95:        50 s -> 14 min
az-c same-zone route ratio:    83% -> 11%
cross-zone spillover limit:    unlimited
poll jitter:                   0s
```

Answer:

1. Trigger, amplifiers, symptoms, impact.
2. First safe mitigation and one bad fix to reject.
3. Capacity math for 35,000 clients polling every 5s with 300 KB catalog responses.
4. Health-check and zone-spillover changes for az-c.
5. Post-incident test plan.

---

## Part 3: Compound Scenario B - Recommender Rollout

A recommendation model rollout raises global CTR but hurts an enterprise tenant.

```text
global CTR:                    +5%
enterprise conversion:         -7%
recommendation p99:            140 ms -> 290 ms
ANN p99:                       20 ms -> 90 ms
inventory feature staleness:   30 s -> 8 min
candidate maxRawCandidates:    2400
rankTopK:                      300
cache key:                     surface:item_id
```

Answer:

1. Why global CTR is unsafe as the rollout decision.
2. First mitigation order across model, candidate sources, inventory freshness, and tenant cache key.
3. Candidate-score math at 18k QPS and rankTopK 300 versus 80.
4. Feature Store checks and A/B guardrails.
5. Abuse and tenant-isolation tests before re-ramp.

---

## Part 4: Compound Scenario C - Agent Tool Side Effects

An agent platform rollout enables a new support connector.
Duplicate emails and coupon credits appear for one tenant.

```text
workflow starts/min:              2,800 -> 3,600
model calls/workflow p95:         7 -> 24
tool calls/workflow p95:          4 -> 17
idempotency hit rate:             89% -> 9%
approval queue depth:             220 -> 9,500
approval onTimeout:               approve
tool idempotency key:             random_uuid
memory tenantFilterRequired:      false
```

Answer:

1. Trigger, amplifiers, symptoms, impact.
2. First scoped kill switch and why not to delete workflow state.
3. Model calls/sec at 3,600 starts/min and p95 24 calls/workflow.
4. Correct idempotency keys for email and coupon tools.
5. Approval timeout, auth, memory, and eval changes before rollback is retried.

---

## Part 5: Transfer Prompts

**T1.** Design a fallback policy when discovery is stale and the recommender's feature store is also stale.

**T2.** Explain how a bad agent tool could corrupt recommendation experiment metadata and how auth/audit would catch it.

**T3.** Compare bounded stale cache in service discovery with stale feature values in recommendation serving.

**T4.** Describe a dashboard that separates LLM serving token latency from agent workflow tool loops.

**T5.** Create one tenant-isolation test that applies to discovery metadata, recommender caches, and agent memory.

**T6.** Name one global mitigation in each module that should usually be rejected because it widens blast radius.

---

## Part 6: Mixed Short Scenarios

Each answer should be 4-8 sentences. Name the invariant, the evidence, and the first scoped mitigation.

**S1. Discovery + retries**

A Go service uses client-side discovery. Registry watches fail for 90 seconds, and clients switch to polling every 3 seconds.
The service owner proposes lowering endpoint TTL from 60 seconds to 1 second so clients find fresh endpoints faster.
Should you approve it? Include the retry/backoff policy you would require.

**S2. Discovery + service identity**

A service registry record includes SPIFFE ID metadata used by clients to choose a mTLS peer.
The registry is stale for 12 minutes after a certificate rotation.
Which paths can use last-known-good endpoints, and which should fail closed?

**S3. Recommendations + Feature Store**

The recommender ranker is unchanged, but conversion drops after a stream job restart.
`user_7d_purchase_count` freshness is 45 minutes against a 5-minute SLA, and null rate rises from 0.3% to 18%.
What do you check before rolling back the model?

**S4. Recommendations + A/B**

A new home feed variant wins CTR by 4% but loses enterprise tenant retention by 2% and increases hide/report actions by 30%.
The PM asks to ship because the experiment is statistically significant globally.
What do you say?

**S5. Recommendations + multi-tenant cache**

A tenant reports seeing items from another tenant only on product detail recommendations.
The cache key is `pdp:{item_id}:{model_version}`.
Name the missing dimensions and the safest immediate mitigation.

**S6. Agents + idempotency**

An agent retries `send_invoice_email` after a 504 from the email provider.
The second attempt uses a new operation id and both emails are delivered.
What idempotency key and verification step should have existed?

**S7. Agents + memory**

A project memory says, \"skip approval for sandbox coupons,\" but the workflow is now operating in production.
What memory metadata and policy check should prevent this instruction from being used?

**S8. Agents + LLM serving distinction**

Agent workflows are expensive and slow. GPU utilization is only 42%, TTFT is healthy, but tool calls per workflow tripled.
Which subsystem do you investigate first and why?

**S9. Agents + human-in-loop**

Approval queue depth hits 8,000. A manager suggests auto-approving requests older than 15 minutes.
When is timeout auto-approval acceptable, and when must it fail closed?

**S10. Cross-topic blast radius**

Name one scoped kill switch for service discovery, one for recommendations, and one for agent tools.
For each, explain why the scoped switch is safer than a global shutdown.


---

## Part 4: Ads / Ticketing / Travel / Trends rapid-fire

**Q40 [ADS]**
Frequency capping at "3 impressions / user / day" is enforced only in the auction ranker. What failure mode remains, and where must the hard gate live?

**Q41 [ADS]**
Pacing underspends early then floods in the last hour. Name the feedback loop and one safer pacing controller.

**Q42 [ADS]**
A single advertiser campaign becomes a Redis hot key for caps. Give two mitigations that preserve correctness.

**Q43 [TREND]**
A hashtag jumps to #1 globally in 90 seconds from one ASN range. What signals distinguish organic vs astroturf before promoting to the UI?

**Q44 [TREND]**
Top-K trending uses a single Kafka partition key = hashtag. What breaks at celebrity scale, and what key design fixes it?

**Q45 [TM]**
Seat hold TTL is 10 minutes; payment capture p99 is 12 minutes during a drop. What inventory failure occurs and the correct sequencing fix?

**Q46 [TM]**
Waiting room admits 50k users but inventory service can safely hold 8k concurrent seats. What capacity check was missed?

**Q47 [FLIGHTS]**
Quoted fare differs from bookable fare 18% of the time. Which freshness/consistency tradeoff failed, and what user-visible contract should the API expose?

**Q48 [FLIGHTS]**
Calendar search fans out to 30 partner APIs with no bulkhead. Partner B is slow. What blast radius control do you add first?

**Q49 [CROSS]**
Map each system to the dominant hot-key risk: ads caps, trending counters, seat holds, fare cache. One sentence each.

---

## Part 5: Compound Scenario C - Drop Day + Sponsored Surge

```text
NORTHSTAR LIVE DROP + SPONSORED PLACEMENT
  19:00 local: limited-drop ticketed experience (Ticketmaster-like holds)
  Parallel: sponsored placements on home + trending rail
  Telemetry T+6m:
    seat_hold_create_success: 62% (was 99%)
    seat_hold_expire_without_pay: +4x
    ads_pacing_error_budget_burn: 11x
    trending_promote_latency_p99: 40ms -> 900ms
    partner_fare_fanout_p99 (unrelated flights tool in same mesh): 1.2s
  Config diffs in last hour:
    ads.frequency_cap_enforce = "soft"   # was hard
    inventory.max_holds_global = 200000  # was 20000
    trending.top_k_window = 30s          # was 15m
```

**C1:** Rank the three user-visible failures by business severity for the next 15 minutes.
**C2:** Which config change is the amplifier for inventory oversell risk? Prove with capacity math.
**C3:** Bad fix gallery: why "disable trending" and "remove all ad caps" are each dangerous.
**C4:** Ordered mitigation T+0..T+15 with cross-system capacity checks.
**C5:** Durable fixes + acceptance criteria for caps, holds, and trending windows.
