"""The value a result is compared with read into a local before the store of that result.

`temp = call(...); work.distance = temp; if (temp < obj->radius) {` stores the result to memory and then loads the
radius. gcc 2.7.2 cannot move the load above the store (both may touch the same memory, `obj` points anywhere), so the
second scheduler keeps the store first and the branch's delay slot stays empty. The target of an 851-instruction N64
ray test (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) loads the radius first and has the store in the branch's
delay slot: `lwc1 $f2,0x4c($s7); c.lt.s $f0,$f2; nop; nop; bc1f L; swc1 $f0,0xa4($sp)`. Reading the radius into its
own local before the store gave exactly that order (5060 -> 4810 in the isolated judge, the six rows of the hunk
equal, nothing else moved); the same comparison against a register variable (the first of the function's two loops)
was already in that order. Hypothesis, not confirmed in the compiler source: the first scheduler orders memory
operations by their original order and the local's load, a separate statement, comes first in it.

`compare_load_stage` offers, for each `x = ...; lhs = x; if (x CMP LOAD) {` where `x` is a declared float or integer
local, `lhs` the store of `x` into memory (a member, an element, a dereference) directly before the `if`, and `LOAD` a
read through a pointer (`M2C_FIELD(p, T *, off)`, `p->field`, `*p`, `p[i]`), the same code with `LOAD` assigned to a
new local of the type of `x` before the store. One child per site, then every site together. The judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'compare_load_stage'
FAMILIES = (FAMILY,)
LIMIT = 8
NAME = '__compare_load'
PLAIN = r'[\w.\[\]]+(?:->[\w.\[\]]+)*'
STORE = re.compile(rf'(?P<indent>[ \t]*)(?P<lhs>{PLAIN}|\*\s*{IDENT})\s*=\s*(?P<x>{IDENT})\s*;[ \t]*\n(?P<head>[ \t]*)if\s*\(\s*(?P=x)\s*(?P<cmp><=|>=|<|>)\s*(?P<load>M2C_FIELD\([^;{{}}]*\)|{IDENT}\s*->\s*{IDENT}|\*\s*{IDENT}|{IDENT}\s*\[[^\];{{}}]*\])\s*\)')


def _local_types(clean, part):
    found = {}
    for kind, names in re.findall(rf'(?m)^\s*((?:unsigned\s+)?(?:f32|f64|float|double|s32|u32|s16|u16|s8|u8|int|short|char))\s+({IDENT}(?:\s*,\s*{IDENT})*)\s*;', clean[part.opening:part.end]):
        for item in names.split(','):
            found[item.strip()] = kind
    return found


def _after_declarations(clean, part):
    """The start of the line after the function's leading run of declarations, else after its opening brace."""
    from .declaration_scope_sink_repairs import DECLARATION
    end = part.opening + 1
    for hit in DECLARATION.finditer(clean, part.opening + 1, part.end):
        if clean[end:hit.start('type')].strip():
            break
        end = hit.end()
    return clean.find('\n', end) + 1


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b|^\s*#', part.body, re.M) or NAME in source:
        return []
    clean = part.clean
    kinds = _local_types(clean, part)
    sites = []
    for hit in STORE.finditer(clean, part.opening, part.end):
        kind = kinds.get(hit['x'])
        if kind is None or hit['lhs'] in kinds:
            continue
        # a call inside the loaded expression, or the stored-to memory named by it, would change what is read
        if re.search(r'\(\s*\w*\s*\)\s*\(|\b\w+\s*\(', hit['load'].replace('M2C_FIELD(', '')):
            continue
        sites.append((hit, kind))
    if not sites:
        return []

    result = []
    for chosen in ([site] for site in sites[:LIMIT]), [sites]:
        for group in chosen:
            if group is sites and len(sites) < 2:
                continue
            edits = []
            declarations = []
            for number, (hit, kind) in enumerate(group):
                local = f'{NAME}{number}'
                declarations.append(f'    {kind} {local};\n')
                load = source[hit.start('load'):hit.end('load')]
                edits.append((hit.start('load'), hit.end('load'), local))
                edits.append((hit.start(), hit.start(), f'{hit["indent"]}{local} = {load};\n'))
            at = _after_declarations(clean, part)
            edits.append((at, at, ''.join(declarations)))
            result.append((FAMILY, edit(source, edits)))
    return result
