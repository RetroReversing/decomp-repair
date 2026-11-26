"""A scaled index written back into the variable it came from before the narrowed value is read.

    t = ((v & 0xFFFF) * 6) & 0xFFFF;     ->     i = v & 0xFFFF;  v = i * 6;  t = v & 0xFFFF;

m2c folds the product into the expression that narrows it. A target built without the scheduler (GCC 2.7.2 `-O1`) can
show the original's two steps in its registers: `andi $v1,$a1,0xffff; sll/addu ...; sll $a1,$v0,1; andi $v0,$a1,0xffff`,
the unmasked value in its own register and the product written back into the argument's register. The folded form (or one
local for both) keeps them in temporaries, and 25 points of register rows stay on a 63-instruction table lookup that the
split form matched. The allocation reading is a hypothesis; the judge decides.

scaled_carrier_writeback
    `(OPERAND * K) & M` or `(OPERAND << K) & M` where OPERAND is `v`, `(v)` or `(v & N)`, K, M and N integer literals,
    v a 32-bit integer local or parameter named once in its statement and not read after it. Children: with a new local
    i, `i = v & N; v = i * K;` before the statement and the expression written `v & M` (N from the operand, or from a
    `v &= N;` statement just before, which the split replaces); and, with no mask on v, `v = v * K;` alone.
    At most 8.
"""
import re

from . import local_flow
from .arm_block_support import brace_pairs, statements
from .integer_repair_support import IDENT, NUMBER, _address_taken, edit, view

FAMILY = 'scaled_carrier_writeback'
FAMILIES = (FAMILY,)
LIMIT = 8
WIDE = r'(?:[su]32|int|long|(?:un)?signed(?:\s+(?:int|long))?)'
SITE = re.compile(rf'(?<=[(=])(?P<space>\s*)\(\s*(?:\(\s*(?P<v>{IDENT})(?:\s*&\s*(?P<n>{NUMBER}))?\s*\)|'
                  rf'(?P<bare>{IDENT}))\s*(?P<op>\*|<<)\s*(?P<k>{NUMBER})\s*\)\s*&\s*(?P<m>{NUMBER})(?=\s*[);])')


def _kind(clean, part, name):
    """The 32-bit type `name` is declared with, as a parameter or a local of this function, else None."""
    head = clean[max(clean.rfind('}', 0, part.opening), clean.rfind(';', 0, part.opening)) + 1:part.opening]
    found = re.findall(rf'(?:[(,]\s*)({WIDE})\s+{re.escape(name)}\s*(?=[,)])', head)
    found += re.findall(rf'(?m)^[ \t]*({WIDE})\s+{re.escape(name)}\s*;', clean[part.opening:part.end])
    if len(found) != 1:
        return None
    return ' '.join(found[0].split()), bool(re.search(rf'[(,]\s*{WIDE}\s+{re.escape(name)}\s*[,)]', head))


def _dead_after(part, flow, statement, local, parameter):
    clean = part.clean
    if _address_taken(clean[part.opening:part.end], local):
        return False
    if parameter or local not in flow.names:
        if re.search(r'\b(?:for|while|do|goto)\b', clean[part.opening:part.end]):
            return False
        return not re.search(rf'\b{re.escape(local)}\b', clean[statement[1]:part.end])
    node = flow.at(statement[0])
    if node is None or node.start != statement[0]:
        return False
    after = set().union(*(flow.nodes[n].live for n in node.successors)) if node.successors else set()
    return local not in after


def variants(source, name):
    part = view(source, name)
    if not part or not SITE.search(part.clean, part.opening, part.end):
        return []
    clean = part.clean
    flow = local_flow.analyze(source, name)
    pairs = brace_pairs(clean, part.opening, part.end)
    if flow is None or not pairs:
        return []
    out = []
    for hit in SITE.finditer(clean, part.opening, part.end):
        local = hit['v'] or hit['bare']
        declared = _kind(clean, part, local)
        if not declared:
            continue
        kind, parameter = declared
        block = max((o, c) for o, c in pairs.items() if o < hit.start() < c)
        spans = list(statements(clean, block[0] + 1, block[1]))
        at = next((i for i, (s, e) in enumerate(spans) if s <= hit.start() < e), None)
        if at is None:
            continue
        statement = spans[at]
        text = clean[statement[0]:statement[1]]
        if '{' in text or len(re.findall(rf'\b{re.escape(local)}\b', text)) != 1:
            continue
        if not _dead_after(part, flow, statement, local, parameter):
            continue
        line = source.rfind('\n', 0, statement[0]) + 1
        indent = re.match(r'[ \t]*', source[line:])[0]
        mask, earlier = hit['n'], None
        if not mask and at:
            previous = spans[at - 1]
            self_mask = re.fullmatch(rf'{re.escape(local)}\s*&=\s*({NUMBER})\s*;', clean[previous[0]:previous[1]].strip())
            if self_mask:
                mask, earlier = self_mask[1], previous
        carrier = local + '_unscaled'
        if re.search(rf'\b{carrier}\b', clean):
            continue
        value = (hit.start() + len(hit['space']), hit.end(), f"{local} & {hit['m']}")
        declare = (part.opening + 1, part.opening + 1, f'\n{indent}{kind} {carrier};')
        first = f'{local} & {mask}' if mask else local
        split = f'{carrier} = {first};\n{indent}{local} = {carrier} {hit["op"]} {hit["k"]};\n{indent}'
        if earlier:
            start = earlier[0] + len(clean[earlier[0]:earlier[1]]) - len(clean[earlier[0]:earlier[1]].lstrip())
            edits = [declare, (start, statement[0], split), value]
        else:
            edits = [declare, (statement[0], statement[0], split), value]
        children = [edits]
        if not mask:
            alone = f'{local} = {local} {hit["op"]} {hit["k"]};\n{indent}'
            children.append([(statement[0], statement[0], alone), value])
        for child in children:
            result = edit(source, child)
            if result != source and (FAMILY, result) not in out:
                out.append((FAMILY, result))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 95}  # registry: no wiring
