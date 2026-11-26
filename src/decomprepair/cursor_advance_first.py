"""A cursor advanced after the reads of its fields, `n = p[1]; c = p[2]; p += 6;`, advanced first and read back.

A command interpreter's arms read their operands through the cursor and then step it (`cmd += 6; break;`). Inside the
interpreter's loop the cursor is an induction variable: loop.c reduces the reads to address givs of it, and where the
biv's step sits decides the order the arm comes out in. With the step after the reads the loads come first and the
giv increments (`addiu $s1, $s1, 6; addiu $s5, $s5, 6`) after them; with the step first the increments come first and
every load reads at a negative offset (`lbu $s0, -6($s1)`). The two are the same program, and the step's place also
decides the registers of the arm's tail, which another arm may cross-jump into. An SN GCC 2.8.1 model loader
(sn-n64-281, 618 instructions, its second `gSPModifyVertex` arm): 1480 -> 1335 with this one edit (1430 -> 1285 under
`-mfp32`); the same edit in the arm before it was worse (1285 -> 2220), so each site is its own child. Which order loop.c
keeps is read from the compiler's output, not from its source: a hypothesis about the mechanism, measured on one function.

`variants` finds a step `P += N;` (or `P = P + N;`) of a pointer local, takes the run of statements before it in the
same block back to the arm's label, the block's opening or the last statement that assigns `P` or jumps, and, when
every use of `P` in that run is a constant index `P[k]` or `*P`, moves the step to the head of the run and writes the
reads as `P[k - N]`. A run with a `break`, `continue`, `return`, `goto` or label, or with `&P`, is left alone. One child
per site, the last site first, and one with every site when there are several.
"""
import re

from . import c_scan
from .integer_repair_support import IDENT, NUMBER, _address_taken, edit, view

FAMILY = 'cursor_advance_first'
FAMILIES = (FAMILY,)
LIMIT = 6
STEP = re.compile(
    rf'(?:(?<=[;{{}}:])|^)(?P<head>[ \t]*)(?P<p>{IDENT})\s*'
    rf'(?:\+=\s*(?P<n>{NUMBER})|=\s*(?P=p)\s*\+\s*(?P<m>{NUMBER}))\s*;', re.M)
LABEL = re.compile(rf'\s*(?:case\b[^;{{}}]*?[^:]:(?!:)|default\s*:|(?!default\b){IDENT}\s*:(?!:))')
JUMP = re.compile(r'\b(?:break|continue|return|goto)\b')
NEXT = re.compile(r'[;{(]')


def _number(text):
    text = text.replace(' ', '')
    sign = -1 if text.startswith('-') else 1
    return sign * int(text.lstrip('-').rstrip('uUlL'), 0)


def _items(clean, lo, hi):
    """The top-level statements of a block between `lo` and `hi`, as (start, end) spans (an `if`/`else` chain and a
    `do ... while (...);` are one statement), or None when the text doesn't split cleanly."""
    items, start, at = [], lo, lo
    while True:
        hit = NEXT.search(clean, at, hi)
        if not hit:
            return items if not clean[start:hi].strip() else None
        if hit.group() == '(':
            close = c_scan.close(clean, hit.start(), '(', ')')
            if close < 0 or close >= hi:
                return None
            at = close + 1
            continue
        if hit.group() == '{':
            close = c_scan.close(clean, hit.start())
            if close < 0 or close >= hi:
                return None
            at = close + 1
            if re.match(r'\s*(?:else\b|while\b)', clean[at:hi]):
                continue
            items.append((start, at))
            start = at
            continue
        at = hit.end()
        items.append((start, at))
        start = at


def _run(clean, items, p):
    """The statements before the step that it may move over: back to a label, a jump or an assignment to `p`."""
    modifies = re.compile(rf'(?:\b{p}\s*(?:[-+*/|&^]?=(?!=)|\+\+|--)|(?:\+\+|--)\s*{p}\b)')
    run = []
    for start, end in reversed(items):
        label = LABEL.match(clean, start, end)
        body = label.end() if label else start
        if JUMP.search(clean, body, end) or LABEL.match(clean, body, end) or modifies.search(clean, body, end):
            break
        run.insert(0, (body, end))
        if label:
            break
    return run


def _site(part, step):
    """The edits that move one step to the head of its run and rebase the reads, or None."""
    clean, p = part.clean, step['p']
    amount = step['n'] or step['m']
    n = _number(amount)
    opening = c_scan.enclosing_block(clean, step.start('p'), part.opening)
    if not n or opening < 0:
        return None
    items = _items(clean, opening + 1, step.start('p'))
    run = _run(clean, items, p) if items else []
    if not run:
        return None
    lo, hi = run[0][0], run[-1][1]
    uses = list(re.finditer(rf'\b{p}\b', clean[lo:hi]))
    if not uses:
        return None
    edits = []
    for use in uses:
        at = lo + use.start()
        index = re.match(rf'{p}\s*\[\s*(?P<k>-?\s*{NUMBER})\s*\]', clean[at:hi])
        deref = re.search(r'(?<![\w)\]\s])\s*\*\s*$|(?:^|[(=,;{}!~&|^+\-<>?:])\s*\*\s*$', clean[lo:at])
        if index:
            edits.append((at, at + index.end(), f'{p}[{_number(index["k"]) - n}]'))
        elif deref and not re.match(rf'{p}\s*(?:\+\+|--|\[|->|\.)', clean[at:hi]):
            star = clean.rfind('*', lo, at)
            edits.append((star, at + len(p), f'{p}[{-n}]'))
        else:
            return None
    first = lo + re.match(r'\s*', clean[lo:hi]).end()
    line = clean.rfind('\n', 0, first) + 1
    indent = clean[line:first] if not clean[line:first].strip() else ''
    separator = f'\n{indent}' if indent or line == first else ' '
    edits.append((first, first, f'{p} += {amount};{separator}'))
    step_line = clean.rfind('\n', 0, step.start('p')) + 1
    if not clean[step_line:step.start('p')].strip() and clean[step.end():step.end() + 1] == '\n':
        edits.append((step_line, step.end() + 1, ''))
    else:
        edits.append((step.start('p'), step.end(), ''))
    return edits


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    sites = []
    for step in STEP.finditer(part.clean, part.opening + 1, part.end):
        p = step['p']
        if not re.search(rf'\*\s*{p}\s*[;,=)\[]', part.clean[:step.start()]) or _address_taken(part.body, p):
            continue
        edits = _site(part, step)
        if edits:
            sites.append(edits)
    results = []
    for chosen in [[site] for site in reversed(sites)] + ([sites] if len(sites) > 1 else []):
        text = edit(source, tuple(e for site in chosen for e in site))
        if text != source and (FAMILY, text) not in results:
            results.append((FAMILY, text))
        if len(results) >= LIMIT:
            break
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 700}  # the registry: no caller wiring (registry.py)
