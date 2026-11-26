"""A field read plus an offset, written as the load and then `+=`: one local with two sets instead of a load temp and a sum.

m2c writes `p = *(s32 *)(base + 0x3C) + off;` as one statement. Inside a loop whose body then tests two masks before
it uses `p` (`if ((a & x) && (b & x)) { use(p) }`), GCC 2.7.2 (KMC, N64) keeps the load's temporary and the sum in the
body's first block: that block has four local quantities and local-alloc.c sorts it by priority, so the table pointer
loaded for the same block gets `$v1` and the index `$v0`. The target had `$v0` / `$v1`, and its load of the field ahead
of the sum. Written `p = *(s32 *)(base + 0x3C); p += off;`, the local has two sets and lives across the body's blocks
(global allocation), so the block keeps three local quantities, which local-alloc.c allocates in birth order (the table
pointer first), and the first scheduler (sched.c `birthing_insn_p` needs one set) no longer launches the load
late. Four loops of one function went from 85 to 25 to 0 with this and the next family; every other row was already right.

A proposal rewrites one statement `V = L + R;` (V a local, L a memory read written with `->` or a leading `*`, R an
identifier or a literal, V in neither) as `V = L;` then `V += R;`; each site alone and all sites together. The same
split is offered for the two-statement spelling m2c uses when the load has its own name, `A = L; V = A + R;`, when `A`
is not read again before its next assignment. MIPS only.
"""
import re

from .csource import _blank, find

FAMILY = 'load_sum_split'
FAMILIES = (FAMILY,)
LIMIT = 8

_ID = r'[A-Za-z_]\w*'
_STATEMENT = re.compile(rf'(?m)^([ \t]*)({_ID}) = ([^;{{}}\n]+);')
_PAIR = re.compile(rf'(?m)^([ \t]*)({_ID}) = ([^;{{}}\n]+);[ \t]*\n?[ \t]*({_ID}) = (\2) \+ ({_ID}|\d+|0[xX][0-9A-Fa-f]+);')
_EFFECT = re.compile(r'\+\+|--|(?<![=!<>])=(?!=)|\w\s*\(')


def _python_top_plus(text):
    """Offset of the last `+` that is outside every bracket, or -1."""
    depth, found = 0, -1
    for at, ch in enumerate(text):
        depth += ch in '([' ; depth -= ch in ')]'
        if ch == '+' and depth == 0 and text[at - 1:at] != '+' and text[at + 1:at + 2] not in ('+', '='):
            found = at
    return found


_top_plus = _python_top_plus
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _top_plus(text):
        found = -1
        for at in _scan.top_offsets(text, '+', 2):
            if text[at - 1:at] != '+' and text[at + 1:at + 2] not in ('+', '='):
                found = at
        return found


def _sites(source, clean, opening, closing):
    sites = []
    for m in _STATEMENT.finditer(clean, opening, closing):
        var, rhs = m[2], m[3]
        at = _top_plus(rhs)
        if at <= 0:
            continue
        left, right = rhs[:at].strip(), rhs[at + 1:].strip()
        if not (re.search(r'->|^\*', left) and re.fullmatch(rf'{_ID}|\d+|0[xX][0-9A-Fa-f]+', right)):
            continue
        if re.search(rf'\b{var}\b', left) or right == var or _EFFECT.search(left):
            continue
        if not re.search(rf'(?m)^[ \t]*(?:(?:unsigned|signed|register)\s+)*{_ID}(?:\s+|\s*\*+\s*){var}\s*;', clean[opening:closing]):
            continue
        sites.append((m.start(2), m.end(), m[1], var, source[m.start(3):m.start(3) + at].rstrip(), right))
    for m in _PAIR.finditer(clean, opening, closing):
        first, load, var, right = m[2], m[3], m[4], m[6]
        if first == var or not re.search(r'->|^\s*\*', load) or _EFFECT.search(load) or re.search(rf'\b{var}\b', load):
            continue
        after = clean[m.end():closing]
        again = re.search(rf'(?<![\w.>]){first}\b', after)
        if again and not re.match(r'\s*=(?!=)', after[again.end():]):
            continue
        sites.append((m.start(2), m.end(), m[1], var, source[m.start(3):m.end(3)].strip(), right))
    return sites


def variants(source, name, arch='mips'):
    """Proposals: `V = load + R;` written `V = load;` then `V += R;`, per site and for all sites."""
    if arch != 'mips':
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    closing = clean.rfind('}', 0, span[1])
    if opening < 0 or closing < opening or re.search(r'^\s*#', clean[span[0]:span[1]], re.M):
        return []
    sites = _sites(source, clean, opening, closing)
    if not sites:
        return []

    def build(chosen):
        new = source
        for start, end, pad, var, load, right in sorted(chosen, reverse=True):
            new = new[:start] + f'{var} = {load};\n{pad}{var} += {right};' + new[end:]
        return new

    groups = [[one] for one in sites]
    if len(sites) > 1:
        groups.append(sites)
    out, seen = [], set()
    for group in groups:
        new = build(group)
        if new != source and new not in seen:
            seen.add(new)
            out.append((FAMILY, new))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'arch'), 'order': 60}  # the registry: no caller wiring (registry.py)
