"""A loop's cursor copy written at the top of the body, where m2c wrote it before the loop and again at the bottom.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) voice-picker that walked a chain of 16-bit links. m2c
wrote the walk with the masked copy of the cursor kept up to date by hand:

    pos = cur & 0xFFFF;
    for (;;) {
        if (limit >= pos) { ...; cur = links[cur].index; pos = cur & 0xFFFF; if ((cur & 0xFFFF) != 0xFFFF) continue; }
        break;
    }

cse sees the second `cur & 0xFFFF` of the loop's end test and the copy of it as one expression and the loop's end is
one `andi` plus a `move`. The target has two `andi`s at the loop's end (one for the test and one filling the branch's
delay slot) and one in front of the loop: the copy is the first statement of the body, which reorg copies into the
delay slot of the loop-back branch and which sits in front of the loop on entry. Written that way the three walks of
that function went 1550 -> 1020 (the registers of all three followed).

loop_top_cursor_copy
    `V = E; for (;;) { ... V = E; ... }` becomes `for (;;) { V = E; ... }` when `E` has no call, `++`, `--` or
    assignment, the second copy is the only one in the body, no `continue` of the loop's own comes before it, nothing
    after it in the body touches `V` or assigns anything, and every later read of `V` follows a write of it. One child
    per loop, and one child with all of them when there are two or more. Hypothesis from the match, not from the
    compiler source: a copy that opens the body is not joined by cse to the loop's end test, and reorg then fills the
    loop-back branch's slot with it.

The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .c_scan import close, normal, own_loop_statements
from .guarded_loop_for import _names, _written_before_read
from .integer_repair_support import IDENT, edit, view

FAMILY = 'loop_top_cursor_copy'
FAMILIES = (FAMILY,)
LIMIT = 8
_LOOP = re.compile(
    rf'(?P<pre>(?<![\w.>])(?P<v>{IDENT})\s*=(?!=)\s*(?P<e>[^;{{}}=]+?)\s*;)\s*'
    r'(?:for\s*\(\s*;\s*;\s*\)|while\s*\(\s*1\s*\))\s*\{')
_IMPURE = re.compile(rf'\+\+|--|(?<![=!<>])=(?!=)|\b(?!(?:if|while|for|switch|return|sizeof)\b){IDENT}\s*\(|\bvolatile\b')
_BLOCKED = re.compile(r'\bgoto\b|\bswitch\b')


def _line(source, start, end):
    """(start, end) widened to the whole line when the statement is alone on it."""
    first = source.rfind('\n', 0, start) + 1
    last = source.find('\n', end)
    if not source[first:start].strip() and last >= 0 and not source[end:last].strip():
        return first, last + 1
    return start, end


def _loops(source, clean, low, high):
    found = []
    for hit in _LOOP.finditer(clean, low, high):
        v, e = hit['v'], hit['e'].strip()
        if _IMPURE.search(e) or not re.search(IDENT, e) or v in re.findall(IDENT, e):
            continue
        opening = hit.end() - 1
        closing = close(clean, opening)
        if closing < 0 or _BLOCKED.search(clean[opening:closing]):
            continue
        body = clean[opening + 1:closing]
        copies = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(v)}\s*=(?!=)\s*([^;{{}}=]+?)\s*;', body)
                  if normal(m[1]) == normal(e)]
        if len(copies) != 1:
            continue
        copy = copies[0]
        after = body[copy.end():]
        if _names(after, v) or _IMPURE.search(re.sub(r'[=!<>]=', '', after)):
            continue
        base = opening + 1
        early = [at for at in own_loop_statements(clean, base, base + copy.start(), 'continue')]
        if early or not _written_before_read(clean, closing + 1, low, high, v):
            continue
        pre = _line(source, hit.start('pre'), hit.end('pre'))
        bottom = _line(source, base + copy.start(), base + copy.end())
        top = (opening + 1, opening + 1, f'\n{source[hit.start("pre"):hit.end("pre")]}')
        found.append((pre, bottom, top))
    return found


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    loops = _loops(source, part.clean, part.opening + 1, part.end)[:LIMIT]

    def edits(items):
        return edit(source, [(a, b, '') for item in items for a, b in (item[0], item[1])] + [item[2] for item in items])

    children = [(FAMILY, edits([item])) for item in loops]
    if len(loops) > 1:
        children.append((FAMILY, edits(loops)))
    return children


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
