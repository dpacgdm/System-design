#!/usr/bin/env python3
"""Extract co-located Expert Analysis (and similar answer blocks) into answers/.

Learner files keep the incident/questions stem; worked analysis moves under answers/.
Idempotent: skips if answer file already exists and learner file no longer contains the block.

This is a structural integrity tool — not a quality score.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Start markers (first match wins, searched in order)
START_PATTERNS = [
    re.compile(r"^## Expert Analysis\s*$", re.M),
    re.compile(r"^## 10\.\s*Expert Analysis\s*$", re.M),
    re.compile(r"^# WEEK \d+ RETENTION TEST — ANSWERS\s*$", re.M),
    re.compile(r"^## Scoring Guide \(Self-Check\)\s*$", re.M),
    re.compile(r"^## Scoring Guide \(self-check after worked answers\)\s*$", re.M),
    re.compile(r"^## Full Expert Analysis\s*$", re.M),
    re.compile(r"^## 13\.\s*Full Expert Analysis\s*$", re.M),
]

# End markers: stop extraction before these (keep them in learner file when present)
END_PATTERNS = [
    re.compile(r"^## Hands-On Exercises\s*$", re.M),
    re.compile(r"^## Key Takeaways\s*$", re.M),
    re.compile(r"^## Targeted Reading\s*$", re.M),
    re.compile(r"^## Next Module\s*$", re.M),
    re.compile(r"^## On-Call Drill", re.M),
]

POINTER = """

---

> **Answer key (do not open until you attempt the Ops Sim / questions):**  
> [`{rel}`]({rel})

"""


def week_dir_for(path: Path) -> str | None:
    for part in path.parts:
        if part.startswith("Week-") or part == "Retention-Tests" or part == "Week-16-Final-Mastery":
            return part
    return None


def find_span(text: str) -> tuple[int, int, str] | None:
    starts = []
    for pat in START_PATTERNS:
        m = pat.search(text)
        if m:
            starts.append((m.start(), m.group(0)))
    if not starts:
        return None
    start, label = min(starts, key=lambda x: x[0])

    end = len(text)
    for pat in END_PATTERNS:
        m = pat.search(text, start + 1)
        if m and m.start() < end:
            end = m.start()
    return start, end, label


def process_file(path: Path, dry_run: bool) -> str:
    text = path.read_text(encoding="utf-8")
    span = find_span(text)
    if not span:
        return f"SKIP (no answer block): {path.relative_to(ROOT)}"

    start, end, label = span
    block = text[start:end].strip() + "\n"
    if len(block) < 200:
        return f"SKIP (block too small): {path.relative_to(ROOT)}"

    week = week_dir_for(path)
    if not week:
        return f"SKIP (no week folder): {path.relative_to(ROOT)}"

    if week == "Retention-Tests":
        out = ROOT / "answers" / "Retention-Tests" / f"{path.stem} Answers.md"
        rel = f"../answers/Retention-Tests/{path.stem} Answers.md"
    else:
        out = ROOT / "answers" / week / f"{path.stem} Answers.md"
        # relative from learner file to answers file
        rel = f"../answers/{week}/{path.stem} Answers.md"

    new_text = text[:start] + POINTER.format(rel=rel) + text[end:]
    # Avoid double pointers
    if "> **Answer key" in text[max(0, start - 400) : start]:
        return f"SKIP (already split): {path.relative_to(ROOT)}"

    if dry_run:
        return f"WOULD SPLIT ({len(block)} chars, label={label!r}): {path.relative_to(ROOT)} -> {out.relative_to(ROOT)}"

    out.parent.mkdir(parents=True, exist_ok=True)
    header = f"# Answer Key — {path.stem}\n\n> Open only after attempting the learner file questions.\n\n"
    if not out.exists():
        out.write_text(header + block, encoding="utf-8")
    else:
        # Append if new content not already present
        existing = out.read_text(encoding="utf-8")
        if block[:120] not in existing:
            out.write_text(existing + "\n\n---\n\n" + block, encoding="utf-8")

    path.write_text(new_text, encoding="utf-8")
    return f"SPLIT: {path.relative_to(ROOT)} -> {out.relative_to(ROOT)}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--path", type=str, default=None, help="Single file or directory")
    args = ap.parse_args()

    if args.path:
        p = Path(args.path)
        paths = [p] if p.is_file() else sorted(p.rglob("*.md"))
    else:
        paths = []
        for folder in sorted(ROOT.glob("Week-*")):
            paths.extend(sorted(folder.glob("*.md")))
        paths.extend(sorted((ROOT / "Retention-Tests").glob("*.md")))

    # Do not split answer keys or meta
    paths = [
        p
        for p in paths
        if "answers" not in p.parts
        and "meta" not in p.parts
        and "Worked Answers" not in p.name
        and not p.name.endswith(" Answers.md")
    ]

    for p in paths:
        print(process_file(p, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
