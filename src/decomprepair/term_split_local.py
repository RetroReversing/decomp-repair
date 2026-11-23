"""A constant folded into a sum with a loaded global, computed first in a temporary of its own.

`v = t - 1 + g;` is read by GCC 2.x's front end as `t + (g - 1)`: the constant moves onto the loaded operand, so the
load comes first and the register the sum lives in is the one the load took. A developer who wrote the two steps
(`q = t - 1; v = q + g;`) gets the target's order (`addiu $v0, $a0, -1`, then the load, then the add), and `q` is a
local of one block, which the allocator colours before the sum's register is chosen (295 -> 240 in one 242-instruction
heightmap filter, with the arms' sums `t - 1 + h` and `t + 1 - h`, KMC GCC 2.7.2).

A proposal takes `dst = a +/- K +/- G;` (a local or parameter `a`, a literal `K`, an `extern` integer global `G`) and
writes `tmp = a +/- K; dst = tmp +/- G;`, the temporary a new local of its own, one per site. One child for each site,
and one with every site when there are several (the arms of one chain pay off together). At most 6 proposals."""
import re

from .integer_repair_support import edit, view

FAMILY = 'term_split_local'
FAMILIES = (FAMILY,)
LIMIT = 6

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
_EXTERN = re.compile(rf'(?m)^[ \t]*extern\s+((?:(?:unsigned|signed|const|volatile)\s+)*(?:[su](?:8|16|32)|char|short|int|long))\s+({_ID})\s*;')
_SUM = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<dst>{_ID})[ \t]*=[ \t]*(?P<a>{_ID})[ \t]*(?P<op1>[+-])[ \t]*(?P<k>{_NUM})[ \t]*'
                  rf'(?P<op2>[+-])[ \t]*(?P<g>{_ID})[ \t]*;[ \t]*$')


def variants(source, name, header=''):
    """Proposals: `dst = a - K + G;` written as two statements through a new local."""
    part = view(source, name)
    if not part:
        return []
    kinds = {glob: kind for kind, glob in _EXTERN.findall(header + '\n' + part.clean[:part.opening])}
    if not kinds:
        return []
    used = set(re.findall(_ID, part.clean[part.opening:part.end]))
    sites = [hit for hit in _SUM.finditer(part.clean, part.opening + 1, part.end)
             if hit['g'] in kinds and hit['g'] not in (hit['a'], hit['dst']) and hit['a'] != hit['dst']]
    if not sites:
        return []
    names, counter = [], 0
    while len(names) < len(sites):
        while f'term{counter}' in used:
            counter += 1
        names.append(f'term{counter}')
        counter += 1
    kind = {hit.start(): kinds[hit['g']] for hit in sites}

    def build(chosen):
        edits = []
        for hit, local in chosen:
            text = (f"{hit['indent']}{local} = {hit['a']} {hit['op1']} {hit['k']};\n"
                    f"{hit['indent']}{hit['dst']} = {local} {hit['op2']} {hit['g']};")
            edits.append((hit.start(), hit.end(), text))
        declarations = ''.join(f'\n    {kind[hit.start()]} {local};' for hit, local in chosen)
        edits.append((part.opening + 1, part.opening + 1, declarations))
        return edit(source, edits)

    out = [(FAMILY, build([(hit, local)])) for hit, local in zip(sites, names)]
    if len(sites) > 1:
        out.insert(0, (FAMILY, build(list(zip(sites, names)))))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 96}  # the registry: no caller wiring (registry.py)
