# Design Module Gates

Every system design module must explicitly address these prompts before the
design is considered complete. Keep learner files question-only; place model
responses in the corresponding `answers/.../<Design> Answers.md` file.

## Mandatory prompts

1. **Authn/z trust boundary**
   - Who is authenticated: user, service, device, job, admin, or tenant?
   - Where is the first trust boundary crossed?
   - Which component enforces authorization for every object or action?
   - What token, certificate, session, or workload identity is accepted?
   - What is the fail-closed behavior when identity or policy is unavailable?

2. **Abuse and misuse**
   - Which actors can intentionally or accidentally overload the design?
   - What are the rate, quota, replay, fraud, spam, scraping, or write-amplification paths?
   - Which controls are per-user, per-tenant, per-key, per-IP, per-region, or global?
   - What evidence distinguishes abuse from organic flash traffic?

3. **Multi-tenant isolation, if multi-tenant**
   - What is the tenancy model: shared table, schema, database, topic, cache, shard, cell, or account?
   - Which resources are reserved or quota-protected per tenant or tier?
   - How are tenant identifiers carried through APIs, caches, queues, search, exports, logs, and support tools?
   - Which tenant can be isolated, throttled, migrated, or disabled without harming others?

4. **Unit cost at target scale**
   - What is the primary business unit: request, message, ride, order, document, minute streamed, query, or tenant?
   - What is the unit cost at the stated target scale and peak multiplier?
   - Which line items dominate: compute, storage, replication, egress, NAT, observability, ML inference, third-party APIs, idle headroom, or support?
   - What cost guardrail pages before margin or budget is breached?

5. **Failure blast radius**
   - What is the smallest failing unit: partition, shard, cell, topic, region, tenant, cache key, model, worker pool, or queue?
   - Which dependencies are shared across critical and non-critical paths?
   - What degrades first, what fails closed, and what stays available?
   - Which runbook action could accidentally widen blast radius?
