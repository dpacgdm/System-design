#!/usr/bin/env python3
"""Normalize single-line ASCII boxes (┌─┐ / │ / └─┘) to uniform width, mirroring
fix_boxes.py's double-line (╔═╗) normalizer. Handles both plain content boxes
and multi-column tables (┌─┬─┐ headers, ├─┼─┤ dividers). Trailing text after a
row's final │ is treated as an external annotation and left untouched — it is
NOT counted toward the box width (matches repo style of side notes on rows).

Blocks containing NESTED box-drawing characters inside a content cell (i.e. a
diagram with sub-boxes/arrows) are intentionally SKIPPED — those need a human
redraw, not blind padding, or arrows and nested borders get corrupted.
"""
import glob
import re
import sys
from wcwidth import wcswidth

TOP_RE = re.compile(r"^(\s*)┌([─┬]*)┐(.*)$")
BOT_RE = re.compile(r"^(\s*)└([─┴]*)┘(.*)$")
DIV_RE = re.compile(r"^(\s*)├([─┼]*)┤\s*$")
NESTED_CHARS = set("┌┐└┘")


def width(s: str) -> int:
    w = wcswidth(s)
    return w if w >= 0 else len(s)


def split_row(inner_and_tail: str):
    """Split a │-delimited row into cells + trailing annotation.
    inner_and_tail is everything after the leading │ (which was stripped)."""
    idx = inner_and_tail.rfind("│")
    if idx == -1:
        return None, inner_and_tail
    core, tail = inner_and_tail[:idx], inner_and_tail[idx + 1:]
    cells = core.split("│")
    return cells, tail


def normalize_block(block):
    """block: list of lines from a ┌ top border to matching └ bottom border.
    Returns new list of lines, or None if this block should be skipped
    (contains nested box art or doesn't parse cleanly)."""
    m0 = TOP_RE.match(block[0])
    indent = m0.group(1)
    top_body = m0.group(2)
    top_tail = m0.group(3)
    if top_tail.strip():
        return None  # top border itself has trailing junk -> not a clean box
    n_cols = top_body.count("┬") + 1 if top_body else 1

    rows = []  # list of ('top'|'bot'|'div'|'content', cells_or_None, tail)
    for ln in block:
        mt = TOP_RE.match(ln)
        mb = BOT_RE.match(ln)
        md = DIV_RE.match(ln)
        if mt:
            rows.append(("top", None, None))
            continue
        if mb:
            if mb.group(3).strip():
                return None
            rows.append(("bot", None, None))
            continue
        if md:
            rows.append(("div", None, None))
            continue
        st = ln
        first = st.find("│")
        if first == -1:
            return None
        after = st[first + 1:]
        # Reject if content itself contains nested box-drawing corners —
        # that means a sub-diagram lives inside; a human must redraw it.
        if any(c in after for c in NESTED_CHARS):
            return None
        cells, tail = split_row(after)
        if cells is None:
            return None
        if len(cells) != n_cols:
            # ragged row (doesn't match column count) -> unsafe to auto-fix
            return None
        rows.append(("content", cells, tail))

    # Compute per-column target width
    col_w = [0] * n_cols
    for kind, cells, _tail in rows:
        if kind == "content":
            for i, c in enumerate(cells):
                w = width(c)
                if w > col_w[i]:
                    col_w[i] = w
    if any(w == 0 for w in col_w) and n_cols > 1:
        # an all-empty column is fine (e.g. blank divider row); leave min 1
        col_w = [w if w > 0 else 1 for w in col_w]
    if n_cols == 1 and col_w[0] == 0:
        col_w[0] = 1

    def render_border(left, fill, joint, right):
        return indent + left + joint.join(fill * w for w in col_w) + right

    out = []
    for kind, cells, tail in rows:
        if kind == "top":
            out.append(render_border("┌", "─", "┬", "┐"))
        elif kind == "bot":
            out.append(render_border("└", "─", "┴", "┘"))
        elif kind == "div":
            out.append(render_border("├", "─", "┼", "┤"))
        else:
            padded = []
            for i, c in enumerate(cells):
                w = width(c)
                padded.append(c + " " * max(0, col_w[i] - w))
            line = indent + "│" + "│".join(padded) + "│"
            if tail:
                line += tail
            out.append(line)
    return out


def process(text: str):
    lines = text.split("\n")
    i = 0
    out = []
    fixed = 0
    skipped = 0
    while i < len(lines):
        m = TOP_RE.match(lines[i])
        if m and not m.group(3).strip():
            j = i + 1
            while j < len(lines):
                if BOT_RE.match(lines[j]) or TOP_RE.match(lines[j]):
                    break
                j += 1
            if j < len(lines) and BOT_RE.match(lines[j]):
                block = lines[i:j + 1]
                nb = normalize_block(block)
                if nb is not None:
                    out.extend(nb)
                    fixed += 1
                else:
                    out.extend(block)
                    skipped += 1
                i = j + 1
                continue
        out.append(lines[i])
        i += 1
    return "\n".join(out), fixed, skipped


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    weeks = sys.argv[2:] if len(sys.argv) > 2 else None
    files = sorted(glob.glob(f"{root}/**/*.md", recursive=True))
    if weeks:
        files = [f for f in files if any(w in f for w in weeks)]
    total_fixed = total_skipped = 0
    for path in files:
        text = open(path, encoding="utf-8").read()
        new, fixed, skipped = process(text)
        if new != text:
            open(path, "w", encoding="utf-8", newline="\n").write(new)
        if fixed or skipped:
            print(f"{fixed:3} fixed, {skipped:3} skipped (needs manual review)  {path}")
        total_fixed += fixed
        total_skipped += skipped
    print(f"\nTOTAL: {total_fixed} boxes auto-fixed, {total_skipped} boxes need manual redraw")


if __name__ == "__main__":
    main()
