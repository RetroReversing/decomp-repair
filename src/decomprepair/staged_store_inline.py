"""A run of values computed into locals and stored right after, written as the direct stores.

`x0 = A; x1 = B; *p = x0; *p = x1;` is what a search's staging leaves (decomprepair's own `deferred_stores` writes
it, and so does a saved best that kept it): every load of the run before its first store. The game wrote
`*p = A; *p = B;`: the second load is then made after the first store, and the compiler keeps both loads and both
stores in their places where the staged form folds the two equal loads into one (KMC GCC 2.7.2, 1135 -> 995 in one
function whose pair of equal stores had to stay a pair).

A proposal takes consecutive lines `n = EXPR;` for locals `n`, followed at once by consecutive lines `LHS = n;` that
read each of them once, in the same order, and writes `LHS = EXPR;`; the locals' declarations go too. A local that is
mentioned anywhere else is not staged and stays. Any processor: the text is plain C.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'staged_store_inline'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'

_ASSIGN = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<name>{IDENT})[ \t]*=(?!=)[ \t]*(?P<value>[^;{{}}\n]+);[ \t]*\n')
_STORE = re.compile(rf'(?m)^[ \t]*(?P<target>[^;{{}}\n=]+?)[ \t]*=(?!=)[ \t]*(?P<name>{IDENT})[ \t]*;[ \t]*\n')


def variants(source, name):
    """Proposals: each run of staged values and their stores, written as direct stores."""
    part = view(source, name)
    if not part:
        return []
    clean, out = part.clean, []
    body = clean[part.opening:part.end]
    runs = []
    for hit in _ASSIGN.finditer(clean, part.opening + 1, part.end):
        if runs and runs[-1][-1].end() == hit.start():
            runs[-1].append(hit)
        else:
            runs.append([hit])
    for whole in runs:
        for first in range(len(whole)):  # the staged run is the end of a row of assignments
            run = whole[first:]
            names = [hit['name'] for hit in run]
            if len(set(names)) != len(names):
                continue
            stores, at = [], run[-1].end()
            for number in range(len(run)):
                hit = _STORE.match(clean, at)
                if not hit or hit['name'] != names[number]:
                    break
                stores.append(hit)
                at = hit.end()
            if len(stores) != len(run):
                continue
            counts = [len(re.findall(rf'(?<![\w.>]){n}\b', body)) for n in names]
            declared = [re.search(rf'(?m)^[ \t]*[\w ]+?[ \t]+{n}[ \t]*;[ \t]*\n', body) for n in names]
            # assigned once, read once, declared once: three mentions and nothing else
            if any(count != 3 for count in counts) or not all(declared):
                continue
            text = ''.join(f'{run[i]["indent"]}{stores[i]["target"].strip()} = '
                           f'{source[run[i].start("value"):run[i].end("value")].strip()};\n' for i in range(len(run)))
            edits = [(run[0].start(), at, text)]
            edits += [(part.opening + d.start(), part.opening + d.end(), '') for d in declared]
            out.append((FAMILY, edit(source, edits)))
            break
    return list(dict.fromkeys(out))[:4]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)
