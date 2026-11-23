"""A clamp `if (v >= K) x = C; else x = v;` whose constant arm also writes the dead value: `x = v = C`.

gcc 2.7.2's jump.c (jump_optimize, "Simplify if (...) x = a; else x = b") turns `if (c) x = a; else x = b;` into
`x = b; if (c) x = a;` when the else source `b` is a register, a subreg or a constant and the then arm is exactly one
insn. It runs before cse and again right after it. The hoisted copy then sits beside the compare: the copy's destination
and the flag are both live across the branch, so they cannot share a register, and reorg fills the branch's delay slot
from above. A target whose clamp is `sltiu $v0, $a1, K; bnez $v0, L; move $v0, $a1 (slot); li $v0, C; L:` (the copy in
the slot, the result in the flag's register) was never hoisted: the copy is the else arm, reorg took it from the branch
target, and the result is born after the flag dies.

Writing the constant arm as `x = v = C` keeps the program (the value is dead after the clamp) but makes that arm two
insns, so neither jump pass hoists; cse folds `x = v` to `x = C` and flow deletes the dead `v = C` before allocation, so
the output has the single `li`. On a 172-instruction N64 sound-voice starter (gcc 2.7.2 KMC, -O2) the last clamp's
`$v1` result became the target's `$v0` (15 -> 0). The pass reading is from jump.c and the dumps (.rtl/.jump); the judge
decides.

The shapes: `if (COND) x = C; else x = v;` (either brace style) and the copy form `x = v; if (COND) x = C;` with `v` an
identifier read in COND, `C` an integer literal, and `v` not read again before it is next assigned. Each site is one
child; all sites together are one more.
"""
import re

from .arm_block_support import IDENT
from .integer_repair_support import edit, view

FAMILY = 'clamp_then_chain'
FAMILIES = (FAMILY,)

NUMBER = r'(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*'


def _arm(braced, bare):
    return rf'(?:\{{\s*(?P<{braced}>[^{{}};]+;)\s*\}}|(?P<{bare}>[^{{}};]+;))'


IF_ELSE = re.compile(
    r'\bif\s*\((?P<cond>[^;{}]*)\)\s*' + _arm('t1', 't2') + r'\s*else\s*' + _arm('e1', 'e2'))
COPY_FORM = re.compile(
    rf'(?P<x>{IDENT})\s*=\s*(?P<v>{IDENT})\s*;\s*if\s*\((?P<cond>[^;{{}}]*)\)\s*'
    rf'(?:\{{\s*(?P<t1>[^{{}};]+;)\s*\}}|(?P<t2>[^{{}};]+;))(?!\s*else\b)')
ASSIGN = re.compile(rf'\s*(?P<x>{IDENT})\s*=\s*(?P<rhs>[^=;][^;]*);\s*$')


def _assign(text):
    hit = ASSIGN.fullmatch(text)
    return (hit['x'], hit['rhs'].strip()) if hit else None


def _dead_after(body, start, var):
    """True when `var` is not read in body[start:] before it is next assigned."""
    for hit in re.finditer(rf'\b{re.escape(var)}\b', body[start:]):
        rest = body[start + hit.end():]
        before = body[:start + hit.start()].rstrip()
        if re.match(r'\s*=(?!=)', rest) and not before.endswith(('.', '->')) and not re.search(r'[-+*/%&|^<>!]$', before):
            return True
        return False
    return True


def _sites(part):
    body = part.clean
    lo, hi = part.opening, part.end
    out = []
    for hit in IF_ELSE.finditer(body, lo, hi):
        then = _assign(hit['t1'] or hit['t2'])
        other = _assign(hit['e1'] or hit['e2'])
        if not then or not other or then[0] != other[0]:
            continue
        x, const = then
        var = other[1]
        if not re.fullmatch(NUMBER, const) or not re.fullmatch(IDENT, var) or var == x:
            continue
        if not re.search(rf'\b{re.escape(var)}\b', hit['cond']) or not _dead_after(body, hit.end(), var):
            continue
        out.append((hit.start(), hit.end(), f'if ({hit["cond"].strip()}) {x} = {var} = {const}; else {x} = {var};'))
    for hit in COPY_FORM.finditer(body, lo, hi):
        then = _assign(hit['t1'] or hit['t2'])
        x, var = hit['x'], hit['v']
        if not then or then[0] != x or not re.fullmatch(NUMBER, then[1]) or var == x:
            continue
        if not re.search(rf'\b{re.escape(var)}\b', hit['cond']) or not _dead_after(body, hit.end(), var):
            continue
        out.append((hit.start(), hit.end(), f'if ({hit["cond"].strip()}) {x} = {var} = {then[1]}; else {x} = {var};'))
    return sorted(set(out))


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    sites = _sites(part)
    out = []
    groups = [[site] for site in sites] + ([sites] if len(sites) > 1 else [])
    for group in groups:
        text = edit(source, group)
        if text != source and (FAMILY, text) not in out:
            out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 95}  # the registry: no caller wiring (registry.py)
