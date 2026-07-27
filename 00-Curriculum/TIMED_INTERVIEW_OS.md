# Timed Interview Operating System — SRE FAANG

This is the **execution layer**. Curriculum without this stays “sufficient.”  
Hard gate before claiming interview-ready: pass the Calibration Checklist at the end.

---

## Round clocks

### System design (45 min default)

| Min | Block | Output |
|----:|-------|--------|
| 0–4 | Requirements + constraints + explicit non-goals | Written bullets |
| 4–8 | Capacity / traffic back-of-envelope | QPS, storage, bandwidth |
| 8–18 | High-level design + APIs | 4–7 boxes max |
| 18–32 | Deep dive (1–2 critical paths) | Data flow + failure |
| 32–40 | Failures, scale, tradeoffs | Cascades, mitigations |
| 40–45 | Summarize + open questions | 60s pyramid |

**60 min variant:** add 10 min for multi-region / consistency deep dive.

### Coding (DSA repo) — 35–45 min

| Min | Block |
|----:|-------|
| 0–3 | Restate + examples + constraints |
| 3–8 | Approach + complexity |
| 8–30 | Code |
| 30–38 | Test cases + edge fixes |
| 38–45 | Optimize / discuss follow-ups |

### Behavioral (30 min)

| Min | Block |
|----:|-------|
| 0–1 | Clarify prompt class |
| 1–5 | STAR-L primary |
| 5–20 | Follow-ups |
| 20–28 | Second prompt |
| 28–30 | Close |

### Behavioral (45 min)

Add Principal stretch + second conflict/failure prompt.

---

## Communication under pressure (mandatory)

Every timed mock uses the **Communication scorecard** from `Week-15b/.../Pressure Communication Drills.md`.

**Rules:**

1. Headline first.  
2. Numbers before architecture.  
3. Check-in at least once per 8 minutes in SD.  
4. On interrupt: stop → answer → ask continue vs stay → resume labeled beat.

---

## Failure modes (self-kill patterns)

| Pattern | Fix |
|---------|-----|
| Boiling the ocean | Timebox deep dive to one path |
| No numbers | Capacity block is mandatory |
| Silent coding | Narrate invariants |
| Behavioral monologue | 4 min cap then invite questions |
| Ignoring hints | Treat interviewer as collaborator |

---

## Mock battery (minimum to pass calibration)

| Type | Count | Pass bar |
|------|------:|----------|
| SD timed (Week-15 mocks) | 3 | Rubric Meets Bar + Comms all ≥3 |
| Behavioral timed | 3 | ≥22/32 + Comms all ≥3 |
| Coding timed (DSA) | 3 | Correct + clean + explained |
| SRE LLD timed | 2 | Compiles-in-head API + concurrency story |

---

## Calibration Checklist (interview-ready gate)

```text
[ ] Week-15b story bank cards 1–10 filled
[ ] Behavioral mocks 01–03 Staff pass
[ ] SD mocks: at least 01, 02, 05 Staff pass (or 3 of 5)
[ ] Communication scorecard: no dimension <3 on last 3 mocks
[ ] DSA: 3 timed problems in 7 days Staff pass
[ ] SRE LLD: rate limiter + cache OR worker pool Staff pass
[ ] Company playbook read for target company (`company-playbooks/`)
[ ] No answer keys opened mid-mock for the passing runs
```

Playbooks: [Meta](./company-playbooks/Meta-SRE.md) · [Netflix](./company-playbooks/Netflix-SRE.md) · [Google](./company-playbooks/Google-SRE.md)

Until all boxes are checked, prep — not luck — is still incomplete.
