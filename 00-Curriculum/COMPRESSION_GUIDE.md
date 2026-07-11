# Compression Guide (Depth via Deletion)

Padding destroys learning. Use this when a module exceeds ~2000–2500 lines without proportional new mechanisms.

## Delete first

- Repeated ASCII boxes that restate the previous paragraph  
- AWS service laundry lists without a decision  
- Second and third examples that teach nothing new  
- Motivational filler and tutor-log asides  
- Duplicate Cassandra/Kafka tours already covered earlier (link back instead)

## Keep

- Wrong mental models  
- One crisp mechanism diagram  
- Math that changes a decision  
- Failure trigger → amplifier → blast radius  
- Ops Sim telemetry/config packs  
- Decision tables with constraints

## Process

1. Identify the 5 claims a principal must remember.  
2. Delete anything that does not support those claims or the Ops Sim.  
3. Re-run the module checklist in `QUALITY_RUBRIC.md`.  
4. Prefer 1200 sharp lines over 3000 soft ones.
