"""A run of stores of one constant, written as the chained assignment it was.

    e->d = 0x40;  e->c = 0x40;  e->b = 0x40;  e->a = 0x40;      ->      e->a = e->b = e->c = e->d = 0x40;

A chain loads the constant once into one register and keeps the destination's base in another; separate statements
through absolute addresses make GCC 2.7.2 build each address again (a 243-instruction function at -O1, four adjacent
halfwords: 1360 -> 0). The chain is written with the statements reversed, so the stores happen in the order the source
had them. Offered for each run of two to eight adjacent statements storing the same literal, and for each longer
suffix of such a run. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'constant_store_chain'
FAMILIES = (FAMILY,)
_VALUE = r'-?(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+f?)?)[uUlL]*'
# a statement that stores a literal into an lvalue: no comparison or compound operator before the `=`, no second `=`
_STORE = re.compile(rf'(?<=[;{{}}])(?P<gap>\s*)(?P<lhs>[*(\w][^;{{}}=!<>?]*?(?:->[^;{{}}=!<>?]*?)*)(?<![-+*/%&|^])'
                    rf'\s*=\s*(?P<value>{_VALUE})\s*;')
_DECLARATION = re.compile(r'^(?:(?:const|static|volatile|unsigned|signed|struct)\s+)*[A-Za-z_]\w*(?:\s*\*)*\s+\**[A-Za-z_]')
LIMIT = 16


def _runs(part):
    clean = part.clean
    run = []
    for at in range(part.opening, part.end):
        if clean[at] not in ';{}':
            continue
        hit = _STORE.match(clean, at + 1)
        if not hit:
            continue
        lhs = hit['lhs'].strip()
        if _DECLARATION.match(lhs) or lhs.startswith(('else', 'return', 'case', 'do ')) or lhs.count('(') != lhs.count(')'):
            continue
        entry = (hit.start('lhs'), hit.end(), hit['value'])
        if run and run[-1][1] == at + 1 and run[-1][2] == entry[2]:
            run.append(entry)
        else:
            if len(run) > 1:
                yield run
            run = [entry]
    if len(run) > 1:
        yield run


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for run in _runs(part):
        run = run[:8]
        for first in range(len(run) - 1):
            picked = run[first:]
            targets = [part.clean[a:b].rsplit('=', 1)[0].strip() for a, b, _ in picked]
            chain = ' = '.join(reversed([source[a:a + len(t)] for (a, _, _), t in zip(picked, targets)]))
            out.append((FAMILY, edit(source, [(picked[0][0], picked[-1][1], f'{chain} = {picked[0][2]};')])))
            if len(out) >= LIMIT:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
