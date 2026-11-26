"""A masked constant (`0 & 0xFF`) that the target computes from the live variable it came from.

    var_v1 = 0; ...; var_v0 = 0 & 0xFF;   (goto form: the scan's exit, the value a test reads next)
    var_v1 = 0; ...; var_v0 = var_v1 & 0xFF;

m2c propagates a known constant into an expression, so a mask of the flag that is still zero on this path becomes
`0 & 0xFF`, which the compiler folds to `move $v0, $zero`. The game masked the variable (`v0 = v1 & 0xFF;`, the same
statement the other path of the join executes) and the target has the `andi $v0, $v1, 0xff` on this path too. A N64
string-append function written in m2c's goto form (KMC GCC 2.7.2, 33 instructions) stood at 200 with `0 & 0xFF`; the
label structure (`loop_1`, `block_3`, `block_7`, `block_8`) was already the target's, and that one operand was the only
difference left (200 -> 0).

Children: for a statement `X = K & M;` (K and M integer literals, M a byte or halfword mask `0xFF`/`0xFFFF`/`0xff`)
and each scalar local `L` other than X that is assigned the literal K earlier in the function (`L = K;`), `X = L & M;`.
The mask of the join that already reads `L & M` (a second statement with the same mask) makes `L` the first choice.
When the target's assembly is given, an `andi` with that mask must be in it (a folded constant has none). Nothing is
offered for a function with `volatile`, `asm` or a preprocessor line. Hypothesis, not confirmed in the compiler
source: the fold happens in the front end before the register allocator sees the variable."""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'masked_constant_live_source'
FAMILIES = (FAMILY,)
LIMIT = 6
_MASKED = re.compile(rf'(?m)^(?P<lead>[ \t]*)(?P<lhs>{IDENT})\s*=\s*(?P<k>{NUMBER})\s*&\s*(?P<m>0[xX](?:[fF]{{2}}|[fF]{{4}}))\s*;')
_ASSIGNED = re.compile(rf'(?m)(?<![\w.>])(?P<name>{IDENT})\s*=\s*(?P<k>{NUMBER})\s*;')


def _value(text):
    return int(text.rstrip('uUlL'), 0)


def _has_mask(asm, mask):
    return not asm or bool(re.search(rf'\bandi\s+\$\w+\s*,\s*\$\w+\s*,\s*(?:0x)?{mask[2:].lower()}\b', asm.lower()))


def variants(source, name, asm=''):
    part = view(source, name)
    if not part:
        return []
    body = part.clean
    if re.search(r'\b(?:volatile|asm|__asm__)\b|^\s*#', body[part.opening:part.end], re.M):
        return []
    out = []
    for hit in _MASKED.finditer(body, part.opening, part.end):
        if not _has_mask(asm, hit['m']):
            continue
        k = _value(hit['k'])
        sources = []
        for assigned in _ASSIGNED.finditer(body, part.opening, hit.start()):
            if assigned['name'] != hit['lhs'] and _value(assigned['k']) == k and assigned['name'] not in sources:
                sources.append(assigned['name'])
        rest = body[hit.end():part.end]
        # the variable that the same mask reads on the other path of the join comes first
        sources.sort(key=lambda n: not re.search(rf'\b{re.escape(n)}\s*&\s*{hit["m"]}', rest))
        for local in sources[:3]:
            at = hit.start('k')
            out.append((FAMILY, edit(source, [(at, hit.end('m'), f'{local} & {hit["m"]}')])))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
