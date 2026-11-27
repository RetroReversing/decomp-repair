"""A narrow return type written on a callee, where the target narrows the local the result is compared with.

    volatile short f(s16);                      s32 f(s16);
    s32 hi, lo;                            ->   s16 hi, lo;
    if (hi < f(a) || lo < f(b)) ...             if (f(a) > hi || f(b) > lo) ...

An earlier search finds the `sll`/`sra` of a 16-bit extension in the target and produces it by declaring the callee's
result narrow (`volatile` so it is not reused). The extension then lands on `$v0`, while the target extends the other
side of the compare: the original compared a word the callee returns with 16-bit locals. On a 48-instruction N64 range
check (SN GCC for N64, `-O2 -mips3 -mfp64`) all three edits together are exact (30 -> 0): the callee declared `s32`
alone scored 410, the locals declared `s16` alone 400, both without the call written first 375, and the call written
first alone left 30. A chain that keeps only improving children never gets there.

`variants` offers, for each callee declared in the candidate with a narrow integer result whose calls are compared
with word locals: the declaration widened, those locals narrowed to the callee's old width and each such compare
written call first (together, since only the set is exact); then the same with the compares left in their order.
Behaviour can differ when a local does not fit the narrow width; the exact judge decides. Hypothesis, not confirmed in
the compiler source: the operand written first is evaluated first, so the call comes before the local's extension."""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'compare_narrow_move'
FAMILIES = (FAMILY,)
LIMIT = 6
_NARROW = r'(?:unsigned\s+(?:short|char)|signed\s+(?:short|char)|short|char|[su](?:8|16))'
_DECL = re.compile(rf'(?m)^[ \t]*(?:extern[ \t]+)?(?P<type>(?:volatile\s+)?(?P<base>{_NARROW}))[ \t]+(?P<name>{IDENT})\s*\([^;{{}}]*\)\s*;')
_WIDE = r'(?:(?:unsigned|signed)[ \t]+(?:int|long)|unsigned|int|long|[su]32)'
_LOCAL = re.compile(rf'(?m)^(?P<lead>[ \t]*)(?P<type>{_WIDE})(?P<gap>[ \t]+)(?P<names>{IDENT}(?:[ \t]*,[ \t]*{IDENT})*)[ \t]*;')
_MIRROR = {'<': '>', '>': '<', '<=': '>=', '>=': '<=', '==': '==', '!=': '!='}
_OP = r'(?:<=|>=|==|!=|(?<![<\-])<(?!<)|(?<![>\-])>(?!>))'
_BEFORE = re.compile(r'(?:\(|&&|\|\||\?|(?<![=<>!+\-*/%&|^])=|\breturn)\s*$')  # nothing binds tighter on the left
_AFTER = re.compile(r'\s*(?:\)|&&|\|\||\?|;)')


def _locals(part):
    """{name: its declaration match} of the function's word locals."""
    out = {}
    for hit in _LOCAL.finditer(part.clean, part.opening + 1, part.end):
        for local in re.findall(IDENT, hit['names']):
            out[local] = hit
    return out


def _compares(part, source, callee, local_names):
    """[(start, end, local, call first replacement)] of the compares between a call of `callee` and a word local."""
    out = []
    clean = part.clean
    for hit in re.finditer(rf'(?<![\w.>]){re.escape(callee)}\s*\(', clean[:part.end]):
        if hit.start() <= part.opening:
            continue
        end = close(clean, hit.end() - 1)  # just past the call's `)`
        if end is None:
            continue
        call = source[hit.start():end]
        left = re.search(rf'(?<![\w.>])(?P<x>{IDENT})\s*(?P<op>{_OP})\s*$', clean[part.opening:hit.start()])
        if left and left['x'] in local_names:
            start = part.opening + left.start()
            if _BEFORE.search(clean[:start]) and _AFTER.match(clean, end):
                out.append((start, end, left['x'], f"{call} {_MIRROR[left['op']]} {left['x']}"))
            continue
        right = re.compile(rf'\s*{_OP}\s*(?P<x>{IDENT})\b').match(clean, end)
        if right and right['x'] in local_names and _BEFORE.search(clean[:hit.start()]) and _AFTER.match(clean, right.end()):
            out.append((hit.start(), right.end(), right['x'], None))  # already call first
    return out


def _retype(locals_, chosen, narrow):
    """Edits that declare the `chosen` locals as `narrow`, splitting a shared declaration."""
    out = []
    for hit in {locals_[x].start(): locals_[x] for x in chosen}.values():
        names = re.findall(IDENT, hit['names'])
        kept = [n for n in names if n not in chosen]
        text = f"{narrow} {', '.join(n for n in names if n in chosen)};"
        if kept:
            text = f"{hit['type']} {', '.join(kept)};\n{hit['lead']}{text}"
        out.append((hit.start('type'), hit.end(), text))
    return out


def variants(source, name):
    """The combined move per narrow callee: call first, then with the compares in the order they were written."""
    part = view(source, name)
    if not part:
        return []
    locals_ = _locals(part)
    out = []
    for decl in _DECL.finditer(part.clean, 0, part.opening):
        if decl['name'] == name:
            continue
        compares = _compares(part, source, decl['name'], locals_)
        if not compares:
            continue
        base = ' '.join(decl['base'].split())
        edits = [(decl.start('type'), decl.end('type'), 's32')]
        edits += _retype(locals_, {c[2] for c in compares}, base)
        swaps = [(start, end, text) for start, end, _, text in compares if text]
        if swaps:
            out.append(edit(source, edits + swaps))
        out.append(edit(source, edits))
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 55}  # the registry: no caller wiring (registry.py)
