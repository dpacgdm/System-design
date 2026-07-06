#!/usr/bin/env python3
"""Brutal curriculum audit: sections, aesthetics, depth, artifacts."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Flexible section matchers (gold standard uses topic-specific teaching headers)
SECTION_PATTERNS = {
    "learning_objectives": r"^## Learning Objectives",
    "wrong_mental_models": r"^## Wrong Mental",
    "decision_framework": r"^## Decision Framework",
    "failure_modes": r"^## (Production Failure Patterns|Failure Modes|Production Patterns)",
    "sre_toolkit": r"^## SRE Diagnostic",
    "key_takeaways": r"^## Key Takeaways",
    "targeted_reading": r"^## Targeted Reading",
    "incident_scenario": r"^## (Incident Scenario|Hands-On Exercises|Question \d|Expert Analysis)",
    "expert_analysis": r"^## Expert Analysis",
}

TEACHING_WEEKS = list(range(1, 9))  # Weeks 1-8 teaching modules
DESIGN_WEEKS = list(range(9, 15))
SKIP = {"00-Curriculum", "Retention-Tests", "tools", "README.md"}


def count_lines(p: Path) -> int:
    return len(p.read_text(encoding="utf-8", errors="replace").splitlines())


def check_boxes(text: str) -> list[str]:
    issues = []
    for i, line in enumerate(text.splitlines(), 1):
        if "╔" in line or "╚" in line:
            # Check width consistency within box blocks is hard; check orphan chars
            if line.rstrip().endswith("║") and len(line.rstrip()) < 20:
                issues.append(f"L{i}: suspicious short box line")
        # Mismatched box corners
        if "╠" in line and "╣" not in line and "╬" not in line:
            if not line.strip().startswith("#"):
                issues.append(f"L{i}: orphan horizontal box divider")
    # Orphan ║ at start without box context
    return issues[:5]


def find_duplicates(text: str, min_len: int = 120) -> list[str]:
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
    seen = {}
    dups = []
    for i, line in enumerate(lines):
        if len(line) < min_len:
            continue
        if line in seen:
            dups.append(f"duplicate block (~L{i}): {line[:80]}...")
            if len(dups) >= 3:
                break
        seen[line] = i
    return dups


def audit_file(p: Path) -> dict:
    text = p.read_text(encoding="utf-8", errors="replace")
    rel = p.relative_to(ROOT)
    sections = {}
    for name, pat in SECTION_PATTERNS.items():
        sections[name] = bool(re.search(pat, text, re.MULTILINE | re.IGNORECASE))

    # Teaching depth: count ## headers (proxy for structure)
    h2_count = len(re.findall(r"^## ", text, re.MULTILINE))

    return {
        "path": str(rel),
        "lines": count_lines(p),
        "sections": sections,
        "missing_sections": [k for k, v in sections.items() if not v],
        "box_issues": check_boxes(text),
        "duplicates": find_duplicates(text),
        "generator_artifacts": bool(re.search(
            r"Diagnostic playbook step \d+|Append to:.*Design Configuration Store",
            text
        )),
        "h2_count": h2_count,
        "has_learning_obj": sections["learning_objectives"],
        "has_wrong_models": sections["wrong_mental_models"],
    }


def main():
    teaching_files = []
    design_files = []
    other_files = []

    for p in sorted(ROOT.rglob("*.md")):
        parts = p.parts
        if any(s in SKIP for s in parts) or p.name == "README.md":
            continue
        if "Worked Answers" in p.name or "Compound Scenario" in p.name:
            other_files.append(p)
        elif any(f"Week-{w:02d}" in str(p) for w in DESIGN_WEEKS):
            if "Compound" not in p.name:
                design_files.append(p)
            else:
                other_files.append(p)
        elif any(f"Week-{w:02d}" in str(p) for w in TEACHING_WEEKS):
            teaching_files.append(p)
        elif "Week-15" in str(p) or "Week-16" in str(p):
            other_files.append(p)
        else:
            other_files.append(p)

    print("=" * 70)
    print("TEACHING MODULES (Weeks 1-8) — section compliance & depth")
    print("=" * 70)
    teaching_issues = []
    for p in teaching_files:
        if "Worked Answers" in p.name:
            continue
        r = audit_file(p)
        problems = []
        if r["lines"] < 1200:
            problems.append(f"SHORT ({r['lines']} lines, target 1500+)")
        if not r["has_learning_obj"]:
            problems.append("NO Learning Objectives")
        if not r["has_wrong_models"]:
            problems.append("NO Wrong Mental Models")
        if not r["sections"]["sre_toolkit"]:
            problems.append("NO SRE Diagnostic Toolkit")
        if not r["sections"]["decision_framework"]:
            problems.append("NO Decision Framework")
        if not r["sections"]["failure_modes"]:
            problems.append("NO Failure Modes section")
        if r["duplicates"]:
            problems.append(f"DUPES: {len(r['duplicates'])}")
        if r["generator_artifacts"]:
            problems.append("GENERATOR ARTIFACT")
        if problems:
            teaching_issues.append((r["path"], r["lines"], problems))
            print(f"\n{r['path']} ({r['lines']} lines)")
            for pr in problems:
                print(f"  FAIL {pr}")

    print(f"\nTeaching modules scanned: {len(teaching_files)}")
    print(f"Teaching modules with issues: {len(teaching_issues)}")

    print("\n" + "=" * 70)
    print("DESIGN MODULES (Weeks 9-14)")
    print("=" * 70)
    design_issues = []
    for p in design_files:
        r = audit_file(p)
        problems = []
        if r["lines"] < 1800:
            problems.append(f"SHORT ({r['lines']} lines)")
        if not r["has_learning_obj"]:
            problems.append("NO Learning Objectives")
        if r["generator_artifacts"]:
            problems.append("GENERATOR ARTIFACT")
        if r["duplicates"]:
            problems.append(f"DUPES: {len(r['duplicates'])}")
        if problems:
            design_issues.append((r["path"], problems))
            print(f"\n{r['path']} ({r['lines']} lines)")
            for pr in problems:
                print(f"  FAIL {pr}")

    print("\n" + "=" * 70)
    print("GENERATOR ARTIFACTS & DUPLICATES (all files)")
    print("=" * 70)
    for p in sorted(ROOT.rglob("*.md")):
        if "00-Curriculum" in str(p):
            continue
        r = audit_file(p)
        if r["generator_artifacts"] or r["duplicates"]:
            print(f"\n{r['path']}")
            if r["generator_artifacts"]:
                print("  ✗ generator artifact pattern")
            for d in r["duplicates"]:
                print(f"  ✗ {d}")

    # Summary stats
    all_teaching = [audit_file(p) for p in teaching_files if "Worked Answers" not in p.name]
    avg_lines = sum(r["lines"] for r in all_teaching) / max(len(all_teaching), 1)
    with_both = sum(1 for r in all_teaching if r["has_learning_obj"] and r["has_wrong_models"])
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Teaching modules avg lines: {avg_lines:.0f}")
    print(f"Teaching with LO + Wrong Models: {with_both}/{len(all_teaching)}")
    print(f"Design issues: {len(design_issues)}")
    print(f"Teaching issues: {len(teaching_issues)}")


if __name__ == "__main__":
    main()
