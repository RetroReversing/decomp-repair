"""A loaded value scaled in place (`m = *p; ...; m *= 3;`) written as one expression, `m = *p * 3;`.

An arm that reads a record's count byte and multiplies it by a record size is written by m2c as the load, the stores
that follow it, and then `m *= 3;`. Written `m = *p * 3;`, the load has a pseudo of its own (the multiply's operand is
forced into a register first) instead of loading straight into `m`, and the product is the only set that reaches the
local, so `m` is a join of products and not of loads. On a KMC (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) 87-instruction
N64 record-stream walker (a `switch` whose arms each skip a record whose length is a byte times 1, 2, 3 or 6, then add
one), folding the multiply into the load of the two arms that multiply scored 50 -> 0 once the selector was a single
`u8` (130 -> 100 on the saved best before that), because the join local took `$v0` as in the target and the loaded byte
`$v1`. Folding either arm alone left 50 and 30: the two only pay off together, so a child folds every eligible site at
once, after the children that fold one site. (The register effect is a hypothesis about local-alloc's order; the measured
score is the evidence, and the exact judge decides.)

Only a plain 32-bit integer local that is assigned a value that reads memory (`*p`, `p[1]`, `p->x`), followed within
eight simple statements by `m *= <constant>;`, with nothing between that mentions `m`, branches or labels. Hoisting the
multiply up to the load is then the same program: nothing could have read the unscaled value.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'load_scale_fold'
FAMILIES = (FAMILY,)
SITES = 8
BETWEEN = 8
_KIND = r'(?:(?:unsigned|signed)\s+)?(?:int|long)|[su]32|(?:unsigned|signed)'
_SET = re.compile(rf'(?<![\w.>])(?P<v>{IDENT})\s*=(?!=)\s*(?P<e>[^;{{}}=?:]+?)\s*;')
_STATEMENT = re.compile(r'\s*(?P<s>[^;{}:?]*;)')
_STOP = re.compile(r'\b(?:goto|return|break|continue|case|default|if|else|while|for|do|switch)\b|\+\+|--')
_LOAD = re.compile(r'\[|->|^\s*\*|\(\s*\*')
_SIMPLE = re.compile(rf'\*?\s*{IDENT}(?:\s*\[[^\[\]]*\])?(?:\s*(?:->|\.)\s*{IDENT})*')


def _locals(part):
    names = {}
    for decl in re.finditer(rf'(?:^|(?<=[;{{}}]))\s*(?:{_KIND})\s+({IDENT})\s*;', part.clean[part.opening:part.end]):
        names[decl[1]] = names.get(decl[1], 0)+1
    return {name for name, count in names.items()
            if count == 1 and not re.search(rf'&\s*{re.escape(name)}\b', part.body)}


def _sites(part):
    found = []
    known = _locals(part)
    for hit in _SET.finditer(part.clean, part.opening+1, part.end-1):
        v, e = hit['v'], hit['e']
        if (v not in known or re.search(rf'\b{re.escape(v)}\b', e) or not _LOAD.search(e)
                or re.search(r'\b(?:sizeof)\b', e) or _STOP.search(e)):
            continue
        pos = hit.end()
        for _ in range(BETWEEN+1):
            statement = _STATEMENT.match(part.clean, pos)
            if not statement or pos >= part.end:
                break
            scale = re.fullmatch(rf'\s*{re.escape(v)}\s*\*=\s*({NUMBER})\s*;', statement['s'])
            if scale:
                found.append((hit, statement, scale[1]))
                break
            if re.search(rf'\b{re.escape(v)}\b', statement['s']) or _STOP.search(statement['s']):
                break
            pos = statement.end()
    return found[:SITES]


def _fold(source, part, site):
    hit, statement, factor = site
    expression = source[hit.start('e'):hit.end('e')]
    if not _SIMPLE.fullmatch(expression.strip()):
        expression = '('+expression.strip()+')'
    return [(hit.start('e'), hit.end('e'), f'{expression.strip()} * {factor}'),
            (statement.start(), statement.end('s'), '')]


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    sites = _sites(part)
    out = [(FAMILY, edit(source, _fold(source, part, site))) for site in sites]
    if len(sites) > 1:
        out.insert(0, (FAMILY, edit(source, [e for site in sites for e in _fold(source, part, site)])))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 70}  # the registry: no caller wiring (registry.py)
