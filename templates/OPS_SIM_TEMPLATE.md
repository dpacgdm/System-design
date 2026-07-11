# Ops Sim Template (Production Realism Without Labs)

Copy this structure into a module’s **questions-only** Ops Sim section, or into `Ops-Sims/`.  
Put the full worked response in `answers/...`.

---

## Ops Sim: \<TITLE\>

**Time box:** ___ minutes  
**Severity:** P___  
**Service / domain:** ___  
**Northstar system (if any):** ___

### Rules

1. Answer from memory of the teaching section — do not re-read mid-drill.  
2. Write decisions in order (T+0 → T+60).  
3. Name evidence (metric, log line, config key) for every claim.  
4. Do not open `answers/` until finished.

---

### 1. Scenario stem

```text
WHAT USERS SEE:
  ...

WHAT ON-CALL SEES (alerts):
  ...

BUSINESS CONSTRAINT:
  ...
```

---

### 2. Telemetry pack

```text
METRICS (paste-style):
  ...

LOG LINES:
  ...

TRACES / EXPLAIN / CONSUMER LAG (as relevant):
  ...
```

---

### 3. Config pack (include the wrong one)

```text
# relevant snippet — one of these is wrong or dangerous
...
```

---

### 4. Timeline & decision points

| Time | Event | Your move (write before reading further) |
|------|-------|------------------------------------------|
| T+0 | | |
| T+5 | | |
| T+15 | | |
| T+60 | | |

---

### 5. Questions

**Q1 — Layer & root cause:** Which layer owns the primary symptom? What is the mechanism?

**Q2 — Evidence:** Which 3 signals confirm it? Which popular signal is a red herring?

**Q3 — Sequencing:** Ordered mitigation for the first 15 minutes. What do you **not** do yet?

**Q4 — Bad fix gallery:** Why is fix A dangerous? Why is fix B incomplete?

**Q5 — Capacity / blast radius:** Numbers. What breaks if you redirect/failover/scale now?

**Q6 — Durable fix:** Architecture or config change + acceptance criteria.

**Q7 — Org / runbook (when P1/P0):** Who is informed by T+10? What is pre-authorized vs escalation?

---

### 6. Self-score (after answer key)

| Error type | Did it happen? | Note |
|------------|----------------|------|
| Knowledge gap | | |
| Misread / wrong layer | | |
| Sequencing error | | |
| Capacity miss (same or cross-system) | | |
| Org / runbook miss | | |
| Careless slip | | |

**Pass:** correct layer + safe sequencing + at least one capacity check unprompted.
