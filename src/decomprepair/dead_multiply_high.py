"""m2c's leftover high multiply, which nothing reads, taken out.

When m2c reads a signed division by a constant as `%` or `/` it can still keep the magic-number multiply as a local of
its own (`temp_hi = MULT_HI(x, 0x66666667);`), and pass that local to a call that takes no such argument. The
statement is a second multiply: with it in, the draft computes the product twice and the registers around the division
move. Once the stray argument is gone nothing reads the local. On an N64 function (SN GCC 2.8.1, 124 instructions)
the draft with the argument dropped but the dead multiply kept scored 765 where the same source without it was exact;
no other family removed it (1,412 children).

dead_multiply_high
    A local assigned only from `MULT_HI`/`MULTU_HI`/`DMULT_HI`/`DMULTU_HI` of side-effect-free operands and never
    read loses those statements and its declaration. With the callees' matched definitions at hand, the stray
    arguments are trimmed (callee_arity_trim) and the multiply that leaves dead goes too, as one child. The judge
    decides.
"""
import re

from . import callee_arity_trim
from .integer_repair_support import IDENT, edit, locals_for, refs, view

FAMILY = 'dead_multiply_high'
FAMILIES = (FAMILY,)
ASSIGNMENT = re.compile(r'(?<![\w.>])(?P<name>' + IDENT + r')\s*=\s*(?:\(\s*[su]32\s*\)\s*)?(?:D?MULTU?_HI)\s*\(')
PURE = re.compile(r'(?!.*(?:\+\+|--|(?<![=!<>])=(?!=)))(?:(?!\b(?!(?:M2C_FIELD|sizeof)\b)' + IDENT + r'\s*\().)*', re.S)


def _statement(part, hit):
    """(start, end) of the whole `T = MULT_HI(...);` statement with its line, or None."""
    clean = part.clean
    if clean[:hit.start()].rstrip()[-1:] not in ';{}':
        return None
    depth, close = 0, None
    for at in range(hit.end() - 1, part.end):
        depth += (clean[at] == '(') - (clean[at] == ')')
        if depth == 0:
            close = at
            break
    after = re.compile(r'\s*;').match(clean, close + 1) if close else None
    if not after or not PURE.fullmatch(clean[hit.end():close]):
        return None
    start, end = hit.start(), after.end()
    line = clean.rfind('\n', 0, start) + 1
    newline = clean.find('\n', end)
    if not clean[line:start].strip() and newline >= 0 and not clean[end:newline].strip():
        return line, newline + 1
    return start, end


def _removed(source, name):
    part = view(source, name)
    if not part:
        return None
    sites = {}
    for hit in ASSIGNMENT.finditer(part.clean, part.opening + 1, part.end):
        sites.setdefault(hit['name'], []).append(hit)
    edits = []
    for decl in locals_for(part):
        hits = sites.get(decl['name'])
        if not hits or {r.start() for r in refs(part, decl)} != {h.start('name') for h in hits}:
            continue
        spans = [_statement(part, hit) for hit in hits]
        if None in spans:
            continue
        start, end = decl.start(), decl.end()
        line = part.clean.rfind('\n', 0, start) + 1
        newline = part.clean.find('\n', end)
        if not part.clean[line:start].strip() and newline >= 0 and not part.clean[end:newline].strip():
            start, end = line, newline + 1
        edits += [(start, end, '')] + [(a, b, '') for a, b in spans]
    return edit(source, edits) if edits else None


def variants(source, name, callees=''):
    if '_HI' not in source:
        return []
    out = []
    plain = _removed(source, name)
    if plain:
        out.append((FAMILY, plain))
    for _, trimmed in callee_arity_trim.variants(source, name, callees):
        child = _removed(trimmed, name)
        if child and not _removed(source, name) == child:
            out.append((FAMILY, child))
    return out[:4]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'callees')}
