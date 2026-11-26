"""A staged `|` local that takes one more operand of the final chain, the rest ored in last.

m2c prints a byte replication as `t = (a << 0x18) | (a << 0x10); w = a | (t | (a << 8));`: the partial chain in a
local, the remaining operands ored around it. The game's source had the local carry one more term and the last `or`
take only the rest: `t = (a << 0x18) | (a << 0x10) | (a << 8); w = t | a;`. `|` is associative and commutative, so
the value is the same, but gcc 2.7.2 allocates and schedules the partial chain by the source's association (a
function whose only difference was the operand order of that last `or` scored 5 against its target).

For `T = X;` followed at once by `D = ...;` whose `|` chain (flattened through parentheses) holds `T` exactly once
beside other side-effect-free operands, with `T` used nowhere else, each other operand in turn moves into `T`'s chain
(last, then first), and the final statement ors `T` with what is left (`T` first, then last). The judge picks.
"""
import itertools
import re

from .integer_repair_support import IDENT, edit, view
from .or_chain_order_repairs import UNSAFE, _flatten, _split

FAMILY = 'or_stage_absorb'
FAMILIES = (FAMILY,)
LIMIT = 16
PAIR = re.compile(rf'(?P<head>(?<![\w.>\]])(?P<t>{IDENT})\s*=\s*(?P<x>[^;{{}}=]+?);)(?=(?P<gap>\s*)'
                  rf'(?P<tail>(?P<d>{IDENT}(?:(?:->|\.){IDENT})*)\s*=\s*(?P<y>[^;{{}}=]+?);))')


def _paren(operand):
    return operand if re.fullmatch(rf'{IDENT}|[0-9a-fA-FxX]+[uUlL]*', operand) else f'({operand})'


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|goto|volatile)\b', part.body):
        return []
    clean = part.clean
    out = []
    for hit in PAIR.finditer(clean, part.opening + 1, part.end - 1):
        t, x, y = hit['t'], hit['x'], hit['y']
        if UNSAFE.search(x) or UNSAFE.search(y):
            continue
        xs, ys = _split(x), _split(y)
        if not xs or not ys or len(xs) < 2 or len(ys) < 2:
            continue
        operands = [o.strip() for piece in ys for o in _flatten(piece)]
        if operands.count(t) != 1 or len(operands) < 3 or re.search(rf'\b{t}\b', hit['d']):
            continue
        body = clean[part.opening:part.end]
        declared = len(re.findall(rf'\b{IDENT}\s+{re.escape(t)}\s*;', body))
        if len(re.findall(rf'\b{re.escape(t)}\b', body)) - declared != 2:
            continue  # the assignment and this one use; any other read or write of T stays as it is
        stage = [o.strip() for piece in xs for o in _flatten(piece)]
        rest = [o for o in operands if o != t]
        for z in rest:
            if rest.count(z) != 1:
                continue
            others = [o for o in rest if o != z]
            for new_stage, final in itertools.product(([*stage, z], [z, *stage]), ([t, *others], [*others, t])):
                head = f'{t} = ' + ' | '.join(map(_paren, new_stage)) + ';'
                tail = f'{hit["d"]} = ' + ' | '.join(map(_paren, final)) + ';'
                text = edit(source, [(hit.start('head'), hit.end('head'), head), (hit.start('tail'), hit.end('tail'), tail)])
                if text != source and text not in [o for _, o in out]:
                    out.append((FAMILY, text))
                if len(out) >= LIMIT:
                    return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}
