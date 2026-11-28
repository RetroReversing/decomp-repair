"""A call's result plus a constant, split so an address is set between the call and the sum.

    table = records;                      ->    call_result = angle(x, y);
    heading = angle(x, y) + 0x800;              table = records;
                                                heading = call_result + 0x800;

A pointer set just before such a sum keeps its `lui; addiu` ahead of the call or after the sum's store. A game whose
code reads `jal; lui $v1; addiu $s5, $v1; addiu $v0, K; sw $v0` set it between the two: the address's high half is then
live beside `$v0` and takes `$v1`. A 678-instruction N64 projectile update (SN GCC 2.8.1 `-G0 -mips3 -O2 -mfp64`) went
435 -> 0 with this; the split alone (`call_result_dead_carrier`) stayed at 435, and no family moved the address set
past the call, so the two are one child here.

Both orders of the two statements are read. The pointer set must name neither local of the sum and the call must not
name the pointer. A global the call itself changes would be read after it; the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, NUMBER, view

FAMILY = 'call_sum_address_split'
FAMILIES = (FAMILY,)
LIMIT = 12
_ADDRESS = rf'(?P<pointer>{IDENT})\s*=\s*(?P<address>&?\s*{IDENT}(?:\s*\[\s*{NUMBER}\s*\])?)\s*;'
_SUM = (rf'(?P<target>{IDENT})\s*=\s*(?P<call>(?P<callee>{IDENT})\s*\([^;{{}}]*\))\s*'
        rf'(?P<tail>[+\-]\s*{NUMBER})\s*;')
_PAIRS = (re.compile(rf'(?<![\w.>]){_ADDRESS}\s*{_SUM}'), re.compile(rf'(?<![\w.>]){_SUM}\s*{_ADDRESS}'))


def _one_call(clean, hit):
    """The call group is one call: its brackets close at its end, not before."""
    depth = 0
    text = clean[hit.start('call'):hit.end('call')]
    for at, char in enumerate(text):
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                return at == len(text) - 1
    return False


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    words = set(re.findall(IDENT, clean))
    local = 'call_result'
    while local in words:
        local += '_'
    declarations = re.compile(r'\s*')
    out = []
    for pattern in _PAIRS:
        for hit in pattern.finditer(clean, part.opening + 1, part.end):
            before = clean[:hit.start()].rstrip()[-1:]
            if before not in (';', '{', '}') or not _one_call(clean, hit):
                continue
            pointer, target = hit['pointer'], hit['target']
            names = set(re.findall(IDENT, hit['call']))
            if (pointer == target or pointer in names or hit['callee'] in ('sizeof', 'if', 'while')
                    or set(re.findall(IDENT, hit['address'])) & {pointer, target}):
                continue
            indent = source[source.rfind('\n', 0, hit.start()) + 1:hit.start()]
            indent = indent if not indent.strip() else '    '
            lines = [f'{local} = {source[hit.start("call"):hit.end("call")]};',
                     f'{pointer} = {source[hit.start("address"):hit.end("address")]};',
                     f'{target} = {local} {hit["tail"]};']
            text = source[:hit.start()] + f'\n{indent}'.join(lines) + source[hit.end():]
            opening = part.opening + 1
            opening += declarations.match(source, opening).end() - opening
            out.append((FAMILY, text[:opening] + f's32 {local};\n    ' + text[opening:]))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
