"""The constants a loop stores to one field, written through one local the way the game set them.

Matched on an N64 billboard-strip builder (SN GCC 2.8.1, `-G0 -mips3 -O2`): its vertex loop writes three vertices
per point, each `v->cn[3] = 0;`, `v->cn[3] = 0x80;`, `v->cn[3] = 0;` among the other colour bytes. The target keeps
`addiu $v0,$zero,0x80` inside the loop, right before that vertex's colour stores, and hoists only the 0xFF. Written as
literals, the 0x80 is a set of a fresh pseudo that loop.c moves out (savings 1, life 1, but the 70-insn loop is well
under the threshold, which only falls by 3 per move), so it takes a register of its own for the whole loop and every
register after it shifts (2535). Written through one local (`al = 0x80; v->cn[3] = al; ... al = 0; v->cn[3] = al;`)
the local is set twice in the loop with a use between, `count_loop_regs_set` marks it `may_not_move`, and the constant
stays where the target has it (1930; through a dead local of the function's own, 1350). Read from the loop dump and
loop.c's `count_loop_regs_set` (gcc 2.8.1 source); the exact judge decides each child.

store_constant_web
    For a field (the text after the base of a store, `->cn[3]`) that a loop body stores integer literals to with at
    least two different values, one of them not zero: one child writes the stores from the first non-zero one to the
    last through a new local `t = K; X->f = t;`, one child writes all of them that way. Stores of other fields and the
    values are unchanged; the local is read only by those stores.
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'store_constant_web'
FAMILIES = (FAMILY,)
LIMIT = 8
_LOOP = re.compile(r'\b(?:for|while)\s*\(|\bdo\s*\{')
_STORE = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<base>[A-Za-z_]\w*)(?P<field>(?:->|\.)\w+(?:\[\s*\d+\s*\])?)\s*=\s*'
                    r'(?P<value>0[xX][0-9a-fA-F]+|\d+)\s*;')
_TYPE = 's32'


def _body(clean, loop):
    """(start, end) of the braces of the loop whose keyword starts at `loop`."""
    if clean.startswith('do', loop.start()):
        opening = clean.find('{', loop.start())
    else:
        past = close(clean, loop.end() - 1)
        if not past:
            return None
        rest = re.compile(r'\s*').match(clean, past).end()
        if rest >= len(clean) or clean[rest] != '{':
            return None
        opening = rest
    past = close(clean, opening, '{', '}')
    return (opening, past - 1) if past else None


def _free(clean, base='value'):
    name, k = base, 2
    while re.search(rf'\b{name}\b', clean):
        name, k = f'{base}{k}', k + 1
    return name


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    clean = part.clean
    groups = {}
    for loop in _LOOP.finditer(clean, part.opening + 1, part.end):
        span = _body(clean, loop)
        if not span:
            continue
        for store in _STORE.finditer(clean, span[0], span[1]):
            if store.start() < span[0]:
                continue
            key = (span, re.sub(r'\s+', '', store['field']))
            groups.setdefault(key, []).append(store)
    local = _free(clean)
    declarations = list(re.finditer(r'(?m)^[ \t]*(?:[A-Za-z_]\w*\s+)+\**\s*[A-Za-z_]\w*\s*;', clean[:part.end]))
    declarations = [d for d in declarations if d.start() > part.opening]
    insert = declarations[0].end() if declarations else part.opening + 1
    declaration = (insert, insert, f'\n    {_TYPE} {local};')
    children = []
    for (_, _), stores in groups.items():
        values = [int(s['value'], 0) for s in stores]
        if len(set(values)) < 2 or not any(values) or len(stores) < 2:
            continue
        first = next(i for i, v in enumerate(values) if v)
        for chosen in (stores[first:], stores):
            if len(chosen) < 2 and chosen is not stores:
                continue
            edits = [declaration]
            for s in chosen:
                indent = s['indent']
                edits.append((s.start(), s.end(),
                              f"{indent}{local} = {s['value']};\n{indent}{s['base']}{s['field']} = {local};"))
            children.append(edit(source, edits))
    out = []
    for text in dict.fromkeys(children):
        if text != source:
            out.append((FAMILY, text))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
