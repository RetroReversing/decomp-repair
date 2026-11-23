"""A post-increment copy `x = v++;` written as two locals: `t = v++; x = t;`.

gcc 2.7.2 expands `x = v++` with `x` as the destination of the copy that precedes the increment (`x = v; v = v + 1`),
so the old value lives in `x` alone and combine has nothing left to merge. Written through a second local the copy and
the increment come first and the assignment to `x` follows them (`expand_increment` queues the increment; the later use
of the queued value is taken from a copy made before it): `t = v; v = v + 1; x = t`, and combine cannot fold `t` into
`x` because `v` is set between the two (`reg_set_between_p`). The short-lived `t` takes a temporary register (`$v0`)
and `x`, which is read after the guard that follows, gets a saved one, so the register moves read
`move $v0,$s0 ... addiu $s0,$s0,1 ... move $s2,$v0` in the target where one `move $s2,$s0` came out of the single
local. It also gives `x` the fewer, later references the allocator ranks it by (global.c `find_reg` takes the saved
registers in priority order), which swapped two saved registers in three loops of a mixing-buffer function.

`variants` finds `X = V++;` (or `V--`) statements, `X` an integer local declared as `TYPE X;` and `V` another plain
name, and writes `__repair_postinc_N = V++; X = __repair_postinc_N;` with `TYPE __repair_postinc_N;` declared beside
`X`'s declaration: one child with every such statement and one per statement. Measured on a 370-instruction function
whose three loops each read `index = var_s0++;` (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`): all three together
1150 -> 220 (three loops' `move $v0,$s0` / `move $s2,$v0` pairs and the load that follows the first of them appear as
the target has them); one loop alone changes only that loop. The hypotheses about expansion are from reading expr.c
and combine.c, the judge decides each child.
"""
import re

from .integer_repair_support import IDENT, INTEGER, edit, view

FAMILY = 'postinc_copy_split'
FAMILIES = (FAMILY,)
LIMIT = 8
STATEMENT = re.compile(rf'(?:(?<=[;{{}}])|^)(?P<head>[ \t]*)(?P<dest>{IDENT})\s*=\s*(?P<var>{IDENT})\s*(?P<op>\+\+|--)\s*;', re.M)
DECLARATION = re.compile(rf'(?<![\w*])(?P<type>{INTEGER})\s+(?P<name>{IDENT})\s*;')


def _declaration(part, name, before):
    """The nearest `TYPE name;` before `before`, or None."""
    found = None
    for hit in DECLARATION.finditer(part.clean, part.opening, before):
        if hit['name'] == name:
            found = hit
    return found


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile)\b', part.body) or '__repair_postinc_' in part.clean:
        return []
    sites = []
    for hit in STATEMENT.finditer(part.clean, part.opening, part.end):
        dest, var = hit['dest'], hit['var']
        if dest == var or re.fullmatch(INTEGER, dest) or hit.start() < part.opening:
            continue
        declaration = _declaration(part, dest, hit.start())
        if not declaration:
            continue
        sites.append((hit, declaration))
    if not sites:
        return []

    def build(chosen):
        edits, declared = [], {}
        for number, (hit, declaration) in enumerate(chosen):
            temp = f'__repair_postinc_{number}'
            edits.append((hit.start('dest'), hit.end(), f'{temp} = {hit["var"]}{hit["op"]}; {hit["dest"]} = {temp};'))
            declared.setdefault(declaration.end(), []).append(f' {declaration["type"]} {temp};')
        edits += [(at, at, ''.join(text)) for at, text in declared.items()]
        return edit(source, edits)

    results = []
    for chosen in ([sites] if len(sites) > 1 else []) + [[site] for site in sites]:
        text = build(chosen)
        if text != source and (FAMILY, text) not in results:
            results.append((FAMILY, text))
        if len(results) >= LIMIT:
            break
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 70}  # the registry: no caller wiring (registry.py)
