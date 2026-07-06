#!/usr/bin/env python3
"""Normalize double-line ASCII boxes to uniform width and neutralize
double-width emoji so borders align in every renderer (GitHub, VS Code, terminal)."""
import re, glob, sys
from wcwidth import wcswidth

top_re = re.compile(r'^(\s*)╔═+╗\s*$')
bot_re = re.compile(r'^(\s*)╚═+╝\s*$')
hsep_re = re.compile(r'^\s*╠═*╣\s*$')
lsep_re = re.compile(r'^\s*╟─*╢\s*$')

# Global emoji neutralization (only true double-width offenders that break boxes)
EMOJI = {'✅': '✓', '❌': '✗'}

def fill_len(border_line):
    s = border_line.strip()
    return len(s) - 2  # minus the two corner chars

def normalize_box(block):
    """block: list of raw lines from top border to bottom border. Return new list or None to skip."""
    indent = top_re.match(block[0]).group(1)
    target = fill_len(block[0])
    parsed = []  # (kind, inner)
    for ln in block:
        st = ln.strip()
        if top_re.match(ln):
            parsed.append(('top', None)); continue
        if bot_re.match(ln):
            parsed.append(('bot', None)); continue
        if hsep_re.match(ln):
            parsed.append(('hsep', None)); target = max(target, len(st)-2); continue
        if lsep_re.match(ln):
            parsed.append(('lsep', None)); target = max(target, len(st)-2); continue
        if '║' in ln:
            first = ln.find('║'); last = ln.rfind('║')
            if last == first:
                inner = ln[first+1:]
            else:
                inner = ln[first+1:last]
            parsed.append(('content', inner))
            target = max(target, wcswidth(inner) if wcswidth(inner) >= 0 else len(inner))
            continue
        # unknown interior line -> skip this box to avoid mangling diagrams
        return None
    out = []
    for kind, inner in parsed:
        if kind == 'top':
            out.append(f"{indent}╔{'═'*target}╗")
        elif kind == 'bot':
            out.append(f"{indent}╚{'═'*target}╝")
        elif kind == 'hsep':
            out.append(f"{indent}╠{'═'*target}╣")
        elif kind == 'lsep':
            out.append(f"{indent}╟{'─'*target}╢")
        else:
            w = wcswidth(inner)
            if w < 0: w = len(inner)
            pad = ' ' * max(0, target - w)
            out.append(f"{indent}║{inner}{pad}║")
    return out

def process(text):
    # emoji neutralize first
    for k, v in EMOJI.items():
        text = text.replace(k, v)
    lines = text.split('\n')
    i = 0
    out = []
    boxes_fixed = 0
    while i < len(lines):
        if top_re.match(lines[i]):
            j = i+1
            while j < len(lines) and not bot_re.match(lines[j]) and not top_re.match(lines[j]):
                j += 1
            if j < len(lines) and bot_re.match(lines[j]):
                block = lines[i:j+1]
                nb = normalize_box(block)
                if nb is not None:
                    out.extend(nb); boxes_fixed += 1
                else:
                    out.extend(block)
                i = j+1
                continue
        out.append(lines[i]); i += 1
    return '\n'.join(out), boxes_fixed

if __name__ == '__main__':
    import os
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    files = glob.glob(os.path.join(root, '**/*.md'), recursive=True)
    total = 0
    for fp in files:
        with open(fp, encoding='utf-8') as f:
            orig = f.read()
        new, n = process(orig)
        if new != orig:
            with open(fp, 'w', encoding='utf-8') as f:
                f.write(new)
            print(f"{n:3} boxes  {fp}")
            total += n
    print(f"TOTAL boxes normalized: {total}")
