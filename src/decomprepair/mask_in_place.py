"""A local's mask written back into the local before the statement that reads it (`v &= ~7; use(v);`, or for a
pointer `v = (T *)((u32) v & ~7); use((u32) v);`) where the statement masked it as an operand (`use((u32) v & ~7)`).

On a 398-instruction SN64 GCC 2.8.1 glyph printer (`-G0 -mips3 -O2`) the texture address was staged in a local
(`tex = D_800AE210; tex += idx * 0xD0;`) and stored as `(u32) tex & ~7`. The target ANDs into the address's own
register (`and $t7, $t7, $t5`); the mask written as an operand is a new pseudo that local-alloc puts in `$v0`, and the
block's later cursor registers and stores move with it. With the mask in place in the first block, 1971 -> 340; in
both blocks (one child), 330; the remaining rows were one spill store's place (`copy_sink_to_clobber`, 330 -> 0). The
allocation reading is a hypothesis; the judge decides.

mask_in_place
    An operand `v & K` or `(T) v & K` (v a plain local declared at the top of the function, K an integer literal or
    its `~` complement) standing alone between `(` or `,` and `)` or `,` in a statement that names v once, with v dead
    after the statement (local_flow). Child: `v &= K;` before the statement and the operand written `v` (for an
    integer local), or `v = (P)((T) v & K);` and the operand `(T) v` (for a pointer local of type P); one child per
    site, and one with every site of the same local and mask. At most 16.
"""
import re

from . import local_flow
from .arm_block_support import brace_pairs, statements
from .integer_repair_support import IDENT, edit, view

FAMILY = 'mask_in_place'
FAMILIES = (FAMILY,)
LIMIT = 16
DECL = re.compile(rf'(?m)^[ \t]*((?:signed\s+|unsigned\s+|const\s+)?{IDENT})[ \t]*(\**)[ \t]*({IDENT})[ \t]*;')
MASK = re.compile(rf'(?<=[(,])(\s*)(\(\s*(?P<cast>(?:unsigned\s+)?{IDENT})\s*\)\s*)?(?P<v>{IDENT})\s*&\s*'
                  rf'(?P<k>~?\s*(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*)(?=\s*[),])')


def _top(clean, part):
    found = {}
    for start, end in statements(clean, part.opening + 1, part.end - 1):
        hit = DECL.fullmatch(clean[start:end].strip())
        if not hit:
            break
        found[hit[3]] = (' '.join(hit[1].split()), hit[2])
    return found


def _innermost(pairs, at):
    best = None
    for opening, closing in pairs.items():
        if opening < at < closing and (best is None or opening > best[0]):
            best = (opening, closing)
    return best


def _sites(source, name):
    part = view(source, name)
    if not part or not part.body.strip():
        return []
    clean = part.clean
    if not MASK.search(clean, part.opening, part.end):
        return []
    top = _top(clean, part)
    flow = local_flow.analyze(source, name)
    pairs = brace_pairs(clean, part.opening, part.end)
    if not pairs or flow is None:
        return []
    sites = []
    for hit in MASK.finditer(clean, part.opening, part.end):
        local = hit['v']
        if local not in top:
            continue
        kind, stars = top[local]
        block = _innermost(pairs, hit.start())
        statement = next(((s, e) for s, e in statements(clean, block[0] + 1, block[1]) if s <= hit.start() < e), None)
        if not statement or '{' in clean[statement[0]:statement[1]]:
            continue
        text = clean[statement[0]:statement[1]]
        if len(re.findall(rf'\b{re.escape(local)}\b', text)) != 1 or re.search(rf'&\s*{re.escape(local)}\b', text):
            continue
        node = flow.at(statement[0])
        if node is None or node.start != statement[0]:
            continue
        after = set().union(*(flow.nodes[n].live for n in node.successors)) if node.successors else set()
        if local in after:
            continue
        mask = ' '.join(hit['k'].split()).replace('~ ', '~')
        line = source.rfind('\n', 0, statement[0]) + 1
        indent = re.match(r'[ \t]*', source[line:])[0]
        cast = hit['cast']
        if stars:
            word = cast or 'u32'
            setting = f'{local} = ({kind} {stars})(({word}) {local} & {mask});\n{indent}'
            operand = f'({word}) {local}'
        else:
            setting = f'{local} &= {mask};\n{indent}'
            operand = f'({cast}) {local}' if cast else local
        operand_at = hit.start() + len(hit[1])
        sites.append(((local, mask), [(statement[0], statement[0], setting), (operand_at, hit.end(), operand)]))
    return sites


def variants(source, name):
    sites = _sites(source, name)
    out = []
    groups = {}
    for key, edits in sites:
        groups.setdefault(key, []).extend(edits)
    candidates = [edits for _, edits in sites] + [edits for edits in groups.values() if len(edits) > 2]
    for edits in candidates:
        result = edit(source, edits)
        if result != source and (FAMILY, result) not in out:
            out.append((FAMILY, result))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # registry: no wiring
