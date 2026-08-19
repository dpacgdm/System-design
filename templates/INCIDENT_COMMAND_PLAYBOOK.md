# P0/P1 Incident Command System (ICS) Playbook & Postmortem Template

## 1. Incident Overview Header
- **Incident ID:** INC-2026-XXXX
- **Severity Level:** P0 (Critical Service Outage) / P1 (Major Degradation)
- **Incident Commander (IC):** @sre-lead
- **Communications Lead (CL):** @comm-lead
- **Operations Lead (OL):** @infra-lead
- **Impact Summary:** Brief 2-sentence description of customer-facing impact.

---

## 2. Roles & Responsibilities Matrix (RACI)

| Role | Assigned Name | Primary Responsibilities |
| :--- | :--- | :--- |
| **Incident Commander (IC)** | @name | Owns incident bridge, decision making, prioritization |
| **Operations Lead (OL)** | @name | Executes mitigation commands, inspects telemetry |
| **Communications Lead** | @name | Updates status page every 15 mins, notifies execs |
| **SME Scribe** | @name | Logs timeline events, command execution outputs |

---

## 3. Incident Timeline (UTC)
- **14:00** — Automated Prometheus alert triggered: `HighErrorRateAlert`.
- **14:05** — Incident bridge established; IC declared P0.
- **14:15** — Root cause identified; mitigation command executed.
- **14:30** — Traffic metrics normalized; incident demoted to P2.
- **15:00** — Incident closed.

---

## 4. Root Cause Analysis (5-Whys)
1. **Why did service fail?** ...
2. **Why ...?** ...
3. **Why ...?** ...
4. **Why ...?** ...
5. **Root Cause:** ...

---

## 5. Corrective Action Items (SLA Tracking)

| Action Item | Type | Owner | Target Date | Status |
| :--- | :--- | :--- | :--- | :--- |
| Enforce rate limiting on API gateway | Immediate Fix | @infra-team | 2026-08-25 | OPEN |
| Add PromQL alert for thread starvation | Detection | @monitoring | 2026-08-28 | OPEN |
