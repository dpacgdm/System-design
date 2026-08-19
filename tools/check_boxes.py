#!/usr/bin/env python3
"""Detect ASCII box misalignment: both double-line (curriculum on ..= boxes)
and single-line (table/diagram) box-drawing styles. Reports every broken box
with file, line number, and the mismatch reason. Does not modify files.
"""
import glob
import sys
try:
    from wcwidth import wcswidth
except ImportError:
    def wcswidth(s):
        return len(s)


def width(s: str) -> int:
    w = wcswidth(s)
    return w if w >= 0 else len(s)


def box_width_of(line: str, open_ch: str, close_ch: str) -> int | None:
    """Width of the box portion of a line: from the line start through the
    LAST close_ch. Trailing text after the last border char is an external
    annotation and is intentionally ignored (matches repo style)."""
    idx = line.rfind(close_ch)
    if idx == -1:
        return None
    return width(line[: idx + 1])


# A "fill" char set for double-line borders: pure ═, or ═ with one embedded
# single-line tee (╤/╧) marking a connector attachment point (legitimate style).
def is_double_border(inner: str) -> bool:
    if set(inner) <= {"═"}:
        return True
    tees = sum(1 for c in inner if c in "╤╧")
    rest = set(c for c in inner if c not in "╤╧")
    return tees >= 1 and rest <= {"═"}


# ---------------------------------------------------------------- Double-line
def check_double_line(lines, path, issues):
    for i, line in enumerate(lines):
        st = line.strip()
        if st.startswith("╔") and st.endswith("╗") and is_double_border(st[1:-1]):
            top_w = width(st)
            j = i + 1
            found_bottom = False
            while j < len(lines) and j - i < 400:
                bl = lines[j].strip()
                if bl.startswith("╚") and bl.endswith("╝") and is_double_border(bl[1:-1]):
                    bot_w = width(bl)
                    if bot_w != top_w:
                        issues.append((path, i + 1, f"top/bottom width mismatch: top={top_w} bottom={bot_w} (line {j+1})"))
                    found_bottom = True
                    break
                if bl.startswith("╠") and set(bl.rstrip("╣")[1:]) <= {"═"} and bl.endswith("╣"):
                    w = box_width_of(bl, "╠", "╣")
                    if w != top_w:
                        issues.append((path, j + 1, f"divider width {w} != box width {top_w}"))
                elif bl.startswith("╟") and bl.endswith("╢"):
                    w = box_width_of(bl, "╟", "╢")
                    if w != top_w:
                        issues.append((path, j + 1, f"light divider width {w} != box width {top_w}"))
                elif bl.startswith("║"):
                    w = box_width_of(bl, "║", "║")
                    if w != top_w:
                        issues.append((path, j + 1, f"content line width {w} != box width {top_w}: {bl[:60]}"))
                elif bl == "":
                    pass
                else:
                    break
                j += 1
            if not found_bottom and j < len(lines) and j - i < 400:
                issues.append((path, i + 1, "top border with no matching bottom border found"))


# ---------------------------------------------------------------- Single-line
def check_single_line(lines, path, issues):
    for i, line in enumerate(lines):
        st = line.strip()
        if st.startswith("┌") and st.endswith("┐") and set(st[1:-1]) <= {"─", "┬"}:
            top_w = width(st)
            j = i + 1
            found_bottom = False
            while j < len(lines) and j - i < 400:
                bl = lines[j].strip()
                if bl.startswith("└") and bl.endswith("┘") and set(bl[1:-1]) <= {"─", "┴"}:
                    bot_w = width(bl)
                    if bot_w != top_w:
                        issues.append((path, i + 1, f"single-line box top/bottom mismatch: top={top_w} bottom={bot_w} (line {j+1})"))
                    found_bottom = True
                    break
                if bl.startswith("├") and bl.endswith("┤"):
                    w = box_width_of(bl, "├", "┤")
                    if w != top_w:
                        issues.append((path, j + 1, f"single-line divider width {w} != box width {top_w}"))
                elif bl.startswith("│"):
                    w = box_width_of(bl, "│", "│")
                    if w != top_w:
                        issues.append((path, j + 1, f"single-line content width {w} != box width {top_w}: {bl[:60]}"))
                elif bl == "":
                    pass
                else:
                    break
                j += 1


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    weeks = sys.argv[2:] if len(sys.argv) > 2 else None
    files = sorted(glob.glob(f"{root}/**/*.md", recursive=True))
    if weeks:
        files = [f for f in files if any(w in f for w in weeks)]
    issues = []
    for path in files:
        text = open(path, encoding="utf-8", errors="replace").read()
        lines = text.split("\n")
        check_double_line(lines, path, issues)
        check_single_line(lines, path, issues)
    if not issues:
        print("No box misalignments found.")
        return
    cur = None
    for path, lineno, msg in issues:
        if path != cur:
            print(f"\n=== {path} ===")
            cur = path
        print(f"  L{lineno}: {msg}")
    print(f"\nTOTAL issues: {len(issues)}")


if __name__ == "__main__":
    main()
