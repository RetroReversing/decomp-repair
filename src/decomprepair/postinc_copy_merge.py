"""A value read into a local and stored back plus one, `t = G; G = t + 1;`, written as the post-increment `t = G++;`.

m2c spells a global counter's post-increment (`id = D_8017B220++;`) as two statements through the old value's local.
The two compile differently: from `t = G; G = t + 1;` the local is the destination of the load and the increment
reads it, so the old value lives in one register from the load on; from `t = G++;` `expand_increment` loads into a
temporary of its own, increments and stores that, and copies the old value into `t` after it (`lw $v1; addiu $v0,
$v1,1; sw $v0; move $s5,$v1`). With `t` read after calls, the target keeps the copy in a saved register and the
temporary in `$v1`; the m2c form loads straight into the saved register, and every register after it moves. An SN GCC
2.7.2 (sn-n64-272-0001, `-G8 -mips2 -O2`) audio sequence starter, 121 instructions: 415 -> 50 with this one edit, then
0 with the voice and sequence records typed and the chained stores in the target's order.

`variants` finds adjacent statements `T = G; G = T + 1;` (also `G = 1 + T`, and `G = T - 1` as `G--`), `T` and `G`
different plain names, and writes `T = G++;`. One child with every such pair, and one per pair when there are several.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'postinc_copy_merge'
FAMILIES = (FAMILY,)
LIMIT = 8
PAIR = re.compile(
    rf'(?:(?<=[;{{}}])|^)(?P<head>[ \t]*)(?P<temp>{IDENT})\s*=\s*(?P<var>{IDENT})\s*;\s*'
    rf'(?P=var)\s*=\s*(?:(?P=temp)\s*(?P<op>[+-])\s*1|1\s*\+\s*(?P=temp))[uU]?\s*;', re.M)


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    sites = [hit for hit in PAIR.finditer(part.clean, part.opening, part.end)
             if hit['temp'] != hit['var'] and hit.start() > part.opening]
    if not sites:
        return []

    def build(chosen):
        return edit(source, [(hit.start('temp'), hit.end(),
                              f'{hit["temp"]} = {hit["var"]}{"--" if hit["op"] == "-" else "++"};') for hit in chosen])

    results = []
    for chosen in ([sites] if len(sites) > 1 else []) + [[site] for site in sites]:
        text = build(chosen)
        if text != source and (FAMILY, text) not in results:
            results.append((FAMILY, text))
        if len(results) >= LIMIT:
            break
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 70}  # the registry: no caller wiring (registry.py)
