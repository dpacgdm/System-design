# Answer Key - Design Google Docs

> Open only after attempting the learner file questions.

This key is written for principal/staff-level self-review.
A passing answer should name the irreversible decisions, trust boundaries, highest-amplification actors, unit economics, and smallest safe blast-radius boundary.
It should also say what to turn off first during an incident without corrupting the correctness-critical path.

## Principal Model Answer - What Excellent Looks Like

1. Explains OT or CRDT convergence invariant.
2. Uses durable op log plus periodic snapshots.
3. Separates presence from edits.
4. Handles revision gaps and offline/reconnect.
5. Defines repair using server-side replay, not client truth.

## Ops Sim / Incident Model Answer

### Most likely bug class

1. v2.14.0 transform optimization mishandled concurrent insert/delete or structural ops at same/overlapping offset.
2. Single doc_id dominates transform_failed logs, implying deterministic op sequence not random infrastructure failure.
3. revision_gap_fetch spike and text reverting mean clients could not apply server-acked transformed ops.
4. Memoization or fast-path transform likely omitted context such as offset ordering, revision, or operation span.

### Immediate mitigation

1. Rollback transform library immediately.
2. Put hot affected doc_ids into read-only to stop divergence while preserving reads.
3. Throttle reconnect/gap fetch for affected docs to protect collab workers.
4. Export immutable op-log ranges and current snapshots for forensic replay.
5. Notify users on affected docs that editing is temporarily paused.

### Find and repair diverged documents

1. Query transform_failed, checksum_mismatch, and revision_gap_fetch grouped by doc_id and revision range.
2. Run checksum bot over top active docs and all docs touched during bad deploy window.
3. Replay immutable op logs offline using previous-good transform library from last known-good snapshot.
4. Compare canonical checksum to stored/client checksums and produce repair snapshot.
5. Apply server-signed repair event at a new revision; force clients to hard refresh after ack.

### Prevent recurrence

1. Property-test transform matrix over op pairs, structural ops, random concurrent sequences, and million-op fuzz.
2. Canary transform library on small doc cohort with checksum shadowing.
3. Replay production anonymized op logs before deploy.
4. Gate rollout on transform_failed and revision_gap_fetch leading indicators.
5. Keep fast-path optimization behind doc-scoped kill switch.

---

## Design Gates (mandatory) - Principal-Depth Model Responses

### Gate 1 - Authn/z trust boundary

1. Principal inventory: document users, browser/mobile clients, WebSocket gateways, collab/OT service, presence service, snapshot workers, export workers, sharing/admin actors, support operators
2. First untrusted boundary: ALB/WebSocket gateway before collab service and document API
3. Final authorization decision: Document service using ACL/share policy for read/comment/edit/owner actions before accepting ops or snapshots
4. Accepted identity artifacts: session cookie/OAuth bearer, document capability link where allowed, WebSocket session token, workload identity for workers, support break-glass token
5. Service-to-service trust: mTLS/SPIFFE workload identity plus short-lived service tokens
6. Public clients never choose tenant/user/object IDs without server-side policy checks.
7. Admin/support access requires break-glass approval, reason codes, scoped duration, and immutable audit logs.
8. Background workers carry job identity and original actor context where user intent matters.
9. Capability or signed URL tokens are scoped to one object, operation, expiry, and content hash where applicable.
10. Identity or policy outage behavior: edits, sharing changes, export, and support access fail closed; already-open docs may go read-only; presence can degrade or disappear
11. Read-only degraded mode is acceptable only for explicitly public or previously authorized cached data.
12. Writes, deletes, money movement, admin actions, and privacy-sensitive reads fail closed.
13. Audit events include actor, subject, tenant/context, decision, policy version, request ID, and source IP/device.
14. Cross-region failover preserves auth state; it never bypasses policy to restore availability.
15. A good answer draws this trust boundary before drawing caches, queues, or databases.
16. Model summary: Each operation is authorized against the document ACL at the server revision; a connected socket is not permission to edit forever.

### Gate 2 - Abuse and misuse

1. Highest amplification actor: one hot document with many collaborators producing transform work, gap fetches, presence updates, and reconnect storms
2. Authenticated abuse surfaces: edit ops, comments, share links, exports, gap fetch, WebSocket reconnect, presence spam, snapshot repair
3. Quota dimensions: per-user edits/sec, per-document collaborators, per-doc op rate, per-IP reconnects, per-tenant export, per-region collab workers, global hot-doc cap
4. Global safety caps are separate from per-principal quotas so one bug cannot consume the fleet.
5. Entity-key limits protect hot keys even when all callers are legitimate.
6. Worker concurrency limits protect downstream stores from replay storms and fan-out storms.
7. Retry budgets are finite, jittered, and tied to user intent or idempotency keys.
8. Retry hazard: clients reconnecting and replaying ops while transform bug causes revision gaps, multiplying gap fetch and reset load
9. Telemetry separating flash crowd from abuse: ack latency, transform failures by doc_id/op pair, revision gap fetch, reconnect/sec, op log growth, snapshot lag, presence fan-out, checksum mismatch
10. Organic spikes preserve normal identity diversity; attacks show skewed principals, IPs, clients, or entities.
11. Abuse controls emit allow/deny/throttle decisions into a stream suitable for forensics.
12. Degradation sheds optional work before it rejects correctness-critical operations.
13. Runbooks say when to pause producers, disable retries, or drop optional enrichments.
14. A good answer includes both prevention and incident-time containment.
15. A weak answer only says add rate limiting without keys, budgets, or kill switches.
16. Model summary: Hot documents and reconnect storms are collaboration hot keys; per-document limits and read-only isolation are mandatory.

### Gate 3 - Multi-tenant isolation

1. Tenancy model: workspace/domain tenant, document_id, ACL role, region/cell, storage prefix, export scope
2. Tenant/context propagation: workspace_id, doc_id, user_id, role, revision, session_id, and request_id in ops, snapshots, presence, logs, exports, and support tools
3. Shared resource reservations: per-doc worker lane, WebSocket capacity, op-log write IOPS, snapshot workers, export bandwidth, presence Redis capacity
4. Every cache key, queue message, object prefix, metric label, and support export carries tenant/context explicitly.
5. Missing tenant/context is a policy error, not a default-to-global behavior.
6. Async jobs include context in the payload and in the worker authorization decision.
7. Support tools filter by tenant/context server-side and log the exact export scope.
8. Noisy-neighbor control: put one doc or workspace read-only, disable comments/export, isolate a hot doc lane, roll back one collab version, or force reconnect to one cell
9. Large tenants or hot entities can be isolated into dedicated shards/cells/topics without global migration.
10. Backfills and replays run in tenant-scoped lanes with byte and concurrency budgets.
11. Observability cardinality is bounded so one tenant cannot bankrupt metrics ingestion.
12. Isolation test: user without ACL cannot read doc via op log, snapshot, presence, export, search, cache, or support replay after share removal
13. Disaster recovery restores tenant boundaries, not only bytes.
14. A good answer names logical isolation and physical capacity isolation.
15. A weak answer says tenant_id column and stops there.
16. Model summary: Document ACL/workspace is the security tenant; doc_id is the operational blast-radius boundary.

### Gate 4 - Unit cost at target scale

1. Business unit: one acknowledged edit operation plus one active collaborative session minute
2. Rough unit-cost model: transform CPU plus durable op-log write, snapshot compaction, WebSocket fan-out, presence, and storage/export costs
3. Dominant line items: collab CPU, WebSocket connections, op log storage, snapshot S3/DynamoDB, Redis presence, export rendering, observability for hot docs
4. Include replication, idle headroom, cross-AZ/region transfer, observability, and replay capacity.
5. Separate fixed control-plane cost from variable data-plane cost.
6. Track p50 and p99 cost because tail work often drives autoscaling and queue depth.
7. Chargeback/showback attributes cost by tenant/context, feature, endpoint, and deploy version.
8. Cost alert before margin/SLO breach: cost per 1,000 acknowledged ops and per active doc-minute by workspace/doc size
9. Capacity planning includes event-day peak multiplier, not only daily average.
10. Cost regressions need rollback criteria just like latency regressions.
11. Graceful cost reduction: disable presence/cursors/comments, reduce autosave frequency, put hot doc read-only, delay export and search indexing; never drop acknowledged edits
12. Never reduce cost by weakening correctness, auth, audit, or durability guarantees.
13. Cold storage, compaction, tiering, sampling, and caching are explicit levers with owners.
14. A good answer can defend an order-of-magnitude number on a whiteboard.
15. A weak answer lists cloud products without pricing the business unit.
16. Model summary: Collaborative editing cost is driven by hot docs and transform complexity, not total document count.

### Gate 5 - Failure blast radius

1. Smallest intended failure boundary: doc_id, workspace, collab shard, WebSocket gateway, region, transform library version
2. Shared dependencies between critical and optional paths: collab service shared by edits and gap fetch; Redis presence shared by non-critical cursors; op log shared by repair/export
3. Fail closed: edit authorization, sharing/ACL changes, exports of private docs, support access, repair writes without checksum
4. Serve stale or degraded: presence, comments, search indexing, read-only snapshot
5. Disable first: presence, comments, suggestions, export, search indexing, risky transform optimization, hot-doc editing
6. Runbook hazard that widens blast radius: repairing from client state, truncating op log, forcing global reconnect, or rolling forward transform code without replay proof
7. Bulkheads separate user-facing serving from analytics, backfill, replay, and support tooling.
8. Feature flags are scoped by cell/region/tenant/entity, with a global kill only for known-safe toggles.
9. Queues have dead-letter and replay throttles; replay is never unbounded during recovery.
10. Caches have namespace-level invalidation; global flushes require incident commander approval.
11. Autoscaling must not scale a bad retry loop faster than dependencies can absorb it.
12. Game day: one hot doc triggers transform_failed, revision gaps, rollback leaves diverged docs, then offline replay repairs without losing edits
13. Alerts fire on leading indicators inside the boundary before customers see platform-wide impact.
14. A good answer says what remains working when one shard/cell/topic fails.
15. A weak answer treats multi-region replication as a substitute for blast-radius design.
16. Model summary: A transform regression is contained to affected docs and repaired from immutable op logs, not spread by client refreshes or global resets.

---

## Evaluator Rubric and Red Flags

1. Names the core correctness invariant for real-time collaborative document editor: all clients converge to the same document state for the same ordered op log, and acknowledged edits are not lost during repair
2. Quantifies the dominant scale driver instead of hand-waving capacity.
3. Explains why the fast path is safe under retry, failover, and partial dependency failure.
4. Shows the data lifecycle: hot serving, durable source of truth, compaction/tiering, and replay/repair.
5. Draws control plane and data plane separately where that separation matters.
6. Documents idempotency, deduplication, and ordering where duplicates or loss are unacceptable.
7. Includes observability tied to user impact, not only host metrics.
8. Provides a mitigation order that stops customer pain before root-cause cleanup.
9. States what is intentionally out of scope for V1 and why it is safe to defer.
10. Mentions cost and abuse as first-class design constraints.
11. Uses scoped kill switches rather than global toggles for unknown failure modes.
12. Protects support/admin paths with the same rigor as user-facing APIs.
13. Proves tenant/context isolation through tests and operational controls.
14. Connects incident symptoms to plausible root causes and rejects red herrings.
15. Leaves the system reconciled after rollback; rollback alone is rarely repair.

Common red flags:

1. Treating caches, queues, or CDN as the source of truth when real-time collaborative document editor needs durable reconciliation.
2. Using average QPS when hot keys, celebrities, tenants, regions, prompts, or cells drive the p99.
3. Assuming authenticated users cannot be abusive.
4. Letting background jobs share unlimited capacity with user-serving paths.
5. Failing open on auth, payment, privacy, admin, or data-integrity paths.
6. Global cache flushes, unthrottled replays, or emergency shard changes during peak traffic.
7. No plan for stale data, duplicate events, delayed callbacks, or partial writes.
8. No explicit owner for policy, schema, quota, and configuration changes.
9. No evidence that the design was tested under the exact incident shape.
10. No cost metric at the same granularity as the scaling decision.

Minimum pass bar:

1. Can explain the happy path in under two minutes.
2. Can explain the top three failure modes in under two minutes.
3. Can state the primary data invariant without naming a cloud product.
4. Can point to the exact gate that catches the incident before production.
5. Can say which customer-visible feature is sacrificed first during overload.
6. Can say which action is never allowed during mitigation because it risks data loss or privacy breach.
7. Can produce one line of capacity math for the dominant workload.
8. Can name one blast-radius boundary and one game day that validates it.

---

## Additional Verification Checklist

1. Verify dashboards expose user-impact SLOs for real-time collaborative document editor.
2. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
3. Verify the runbook has a rollback step and a separate reconciliation step.
4. Verify each queue or stream has bounded retry and dead-letter handling.
5. Verify every emergency command is scoped to the smallest safe boundary.
6. Verify post-incident cleanup drains backlog without violating customer promises.
7. Verify schema/config changes cannot bypass review or automated policy checks.
8. Verify tenant/context labels are present in logs without leaking secrets or PII.
9. Verify load tests include skewed traffic, not only uniform distributions.
10. Verify cost dashboards break down the business unit by feature and tenant/context.
11. Verify dashboards expose user-impact SLOs for real-time collaborative document editor.
12. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
13. Verify the runbook has a rollback step and a separate reconciliation step.
14. Verify each queue or stream has bounded retry and dead-letter handling.
15. Verify every emergency command is scoped to the smallest safe boundary.
16. Verify post-incident cleanup drains backlog without violating customer promises.
17. Verify schema/config changes cannot bypass review or automated policy checks.
18. Verify tenant/context labels are present in logs without leaking secrets or PII.
19. Verify load tests include skewed traffic, not only uniform distributions.
20. Verify cost dashboards break down the business unit by feature and tenant/context.
21. Verify dashboards expose user-impact SLOs for real-time collaborative document editor.
22. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
23. Verify the runbook has a rollback step and a separate reconciliation step.
24. Verify each queue or stream has bounded retry and dead-letter handling.
25. Verify every emergency command is scoped to the smallest safe boundary.
26. Verify post-incident cleanup drains backlog without violating customer promises.
27. Verify schema/config changes cannot bypass review or automated policy checks.
28. Verify tenant/context labels are present in logs without leaking secrets or PII.
29. Verify load tests include skewed traffic, not only uniform distributions.

