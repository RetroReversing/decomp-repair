"""A pointer local set once to a global array's element and used only for its members, written as the indexed element.

`ent = &TABLE[count]; ent->kind = 1; ent->t = t; ...` and `TABLE[count].kind = 1; TABLE[count].t = t; ...` are the same
program while nothing between them changes `count`, but GCC 2.x expands them differently: the pointer is one pseudo
holding the whole element address (index scaled, then the base added), the indexed form an address cse builds from the
symbol and the index, with the symbol's `lui`/`addiu` emitted first. The first scheduler then puts the base ahead of the
index load (the index in `$a0`, the base in `$v0`), which no ordering of the pointer form gives.

A 920-instruction N64 ray/triangle test (sn-n64-281 GCC 2.8.1, `-G0 -mips3 -O2 -mgas -meb -mcpu=VR4300 -mhard-float
-mfp32`) that records each hit in a global record array went 352 -> 11 with the record's fourteen member stores written
through `TABLE[count]` instead of a pointer local (measured with the app's judge-worker; one function).

`variants` finds every `P = &ARRAY[INDEX];` whose pointer is a local assigned nowhere else and read only as `P->member`
within the same block, after the assignment, with no call and no change to INDEX (or to P) in between; one child per
such pointer writes each `P->` as `ARRAY[INDEX].` and drops the assignment (the declaration stays when P is still named
elsewhere, and goes when it is not). INDEX is an identifier or an integer literal."""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'element_pointer_direct_index'
FAMILIES = (FAMILY,)
LIMIT = 8
SET = re.compile(rf'(?<![\w.>])(?P<p>{IDENT})\s*=\s*&\s*(?P<a>{IDENT})\s*\[\s*(?P<i>{IDENT}|\d+)\s*\]\s*;')
KEYWORDS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'do', 'else'}


def _block_end(clean, position, lo, hi):
    depth = 0
    for i in range(position, hi):
        c = clean[i]
        if c == '{':
            depth += 1
        elif c == '}':
            if depth == 0:
                return i
            depth -= 1
    return None


def _modifies(text, name):
    n = re.escape(name)
    return re.search(rf'(?<![\w.>]){n}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+\s*{n}\b|--\s*{n}\b|\b{n}\s*(?:\+\+|--)', text)


def _calls(text):
    return any(m[1] not in KEYWORDS for m in re.finditer(rf'\b({IDENT})\s*\(', text))


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = _blank(source)
    lo, hi = part.opening + 1, part.end - 1
    body = clean[lo:hi]
    out = []
    for hit in SET.finditer(body):
        pointer, array, index = hit['p'], hit['a'], hit['i']
        if pointer in (array, index):
            continue
        start, after = lo + hit.start(), lo + hit.end()
        # a local of this function: declared as a pointer in its body
        if not re.search(rf'\b{IDENT}\s*\*\s*{re.escape(pointer)}\s*;', body):
            continue
        uses = [m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(pointer)}\b', clean[lo:hi])]
        uses = [lo + u for u in uses]
        declaration = [u for u in uses if re.match(rf'{re.escape(pointer)}\s*;', clean[u:]) and
                       re.search(r'\*\s*$', clean[lo:u])]
        others = [u for u in uses if u not in declaration and u != start]
        if not others or any(u < after for u in others):
            continue
        if not all(re.match(rf'{re.escape(pointer)}\s*->\s*{IDENT}', clean[u:]) for u in others):
            continue
        end = _block_end(clean, after, after, hi)
        if end is None or others[-1] > end:
            continue
        region = clean[after:others[-1]]
        if _calls(region) or (not index.isdigit() and _modifies(region, index)) or _modifies(region, pointer):
            continue
        # a member store written through the pointer must not itself change the index (`p->n = count++`)
        tail = re.search(r'[^;]*;', clean[others[-1]:end])
        if tail and not index.isdigit() and _modifies(tail.group(0), index):
            continue
        edits = [(start, after + (1 if source[after:after + 1] == '\n' else 0), '')]
        line = source.rfind('\n', 0, start) + 1
        if not source[line:start].strip() and source[after:after + 1] == '\n':
            edits = [(line, after + 1, '')]
        for u in others:
            arrow = re.match(rf'{re.escape(pointer)}\s*->\s*', clean[u:])
            edits.append((u, u + arrow.end(), f'{array}[{index}].'))
        for d in declaration:
            semi = clean.index(';', d) + 1
            dline = source.rfind('\n', 0, d) + 1
            dend = source.find('\n', semi)
            text = source[dline:dend]
            if re.fullmatch(rf'\s*{IDENT}\s*\*\s*{re.escape(pointer)}\s*;\s*', text):
                edits.append((dline, dend + 1, ''))
        out.append((FAMILY, edit(source, edits)))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 900}  # the registry: no caller wiring (registry.py)
