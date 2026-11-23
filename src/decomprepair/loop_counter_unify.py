"""Every counter of one width written as one variable, the way a function that reuses `i` for all its loops has it.

m2c names a counter per loop (`var_s1`, `var_s1_2`, `var_a0_4`, ...), and a saved best from a search keeps a few of them
shared by luck. GCC 2.x hands the saved registers out by floor_log2(uses) * uses / live length (global.c), so one counter
variable for a whole function is one pseudo with every loop's references: it outranks the parameters it competes with and
takes the first saved register, where a counter per loop leaves the parameters in the order of their own few uses. In a
384-instruction function with seven word counters and four byte counters the target kept `arg3` in `$s0` and every loop
counter in `$s1`, and the four byte loops (two table fills and two index walks) in `$a0` with the constant they store in
`$v1`; a counter per loop gave `$s0` to the counters and `$s1` to `arg3`, and the byte loops the registers the other way
round. Merging every counter into one variable per width fixed both (2696 -> 2600 with the walk and the narrow copy; 255 ->
185 for the four byte loops alone).

`loop_counter_roles_repairs`'s merge takes two counters of one declared type; this takes all of one *width* at once (a
`u8`, an `s8` and a `char` counter share a variable whose type is the unsigned one when they differ, a `long` and an `s32`
the shared word type), as one child, since the pairwise merges are each no better until the last. Every counter has to be
set right before its own loop (or in its `for` header) and read nowhere else, and no two loops may overlap, as in
`loop_counter_roles_repairs` (whose `_counters` finds them). The survivor is the first declared counter, and in a second
child the one with the most loops. Proposals only; the compiler and the byte judge decide."""
import re

from .csource import _blank, find
from .loop_address_hoist_repairs import _loops
from .loop_counter_roles_repairs import _apply, _overlap, _rename, _stepped

FAMILY = 'loop_counter_unify'
FAMILIES = (FAMILY,)
WIDTH = {'u8': 'byte', 's8': 'byte', 'char': 'byte', 'unsigned char': 'byte', 'signed char': 'byte',
         'u16': 'half', 's16': 'half', 'short': 'half', 'unsigned short': 'half', 'signed short': 'half',
         's32': 'word', 'u32': 'word', 'int': 'word', 'long': 'word', 'unsigned': 'word', 'unsigned int': 'word',
         'signed int': 'word', 'unsigned long': 'word', 'signed long': 'word'}
UNSIGNED = {'byte': 'u8', 'half': 'u16', 'word': 'u32'}
INTEGER = (r'(?:(?:unsigned|signed)\s+)?(?:char|short|int|long)|[su](?:8|16|32)')
IDENT = r'[A-Za-z_]\w*'
NUMBER = r'(?:-?\d+|0x[0-9A-Fa-f]+)[uUlL]*'
GAP = 400  # how far above its loop a counter's `v = 0;` may sit
AT_MOST = 6  # statements between the set and the loop


def _scan(source, name):
    """({var: (type, (decl start, decl end), [(region start, region end, [mention spans])])}, clean) of the integer locals
    that are only ever set to a number right before a loop that steps them, and read inside those loops."""
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0 or re.search(r'\b(?:asm|__asm__)\b', clean[span[0]:span[1]]):
        return None
    end = span[1]
    loops = _loops(clean, opening, end)
    found = {}
    for decl in re.finditer(rf'(?m)^[ \t]*(?P<type>{INTEGER})[ \t]+(?P<name>{IDENT})[ \t]*;[ \t]*\n', clean[opening:end]):
        var, kind = decl['name'], ' '.join(decl['type'].split())
        spans = (opening + decl.start(), opening + decl.end())
        if var in found or kind not in WIDTH or re.search(rf'(?<![\w.>])&\s*{var}\b', clean[opening:end]):
            continue
        regions = []
        for hit in re.finditer(rf'(?<![\w.>]){re.escape(var)}\s*=(?!=)\s*{NUMBER}\s*;', clean[opening:end]):
            at = opening + hit.end()
            later = [loop for loop in loops if loop[0] >= at and loop[0] - at <= GAP]
            if not later:
                continue
            loop = min(later)
            between = clean[at:loop[0]]
            if (re.search(rf'(?<![\w.>]){re.escape(var)}\b', between) or between.count(';') > AT_MOST
                    or re.search(r'\b(?:goto|return|break|continue|else|switch|case|default|do|for|while)\b|^[ \t]*[A-Za-z_]\w*[ \t]*:(?!:)',
                                 between, re.M)
                    or not _stepped(clean, var, loop)):
                continue
            regions.append((opening + hit.start(), loop[1]))
        for loop in loops:  # `for (v = 0; ...)`: the set is the loop's own first clause
            if re.match(rf'for\s*\(\s*{re.escape(var)}\s*=\s*{NUMBER}\s*;', clean[loop[0]:loop[1]]) and _stepped(clean, var, loop):
                regions.append((loop[0], loop[1]))
        regions = sorted(set(regions))
        if not regions or any(a[1] > b[0] for a, b in zip(regions, regions[1:])):
            continue
        every = [(opening + m.start(), opening + m.end()) for m in re.finditer(rf'(?<![\w.>]){re.escape(var)}\b', clean[opening:end])
                 if not spans[0] <= opening + m.start() < spans[1]]
        owned = [[m for m in every if r[0] <= m[0] < r[1]] for r in regions]
        if sum(len(o) for o in owned) != len(every):
            continue  # a mention outside its loops: a value may flow, so the variable stays
        found[var] = (kind, spans, [(r[0], r[1], o) for r, o in zip(regions, owned)])
    return found, clean


def _widest(found, names):
    """The declaration the one variable takes: the shared type when they agree, else the unsigned one of their width."""
    kinds = {found[v][0] for v in names}
    if len(kinds) == 1:
        return kinds.pop()
    unsigned = [k for k in kinds if k.startswith('u')]
    return unsigned[0] if len(unsigned) == 1 else UNSIGNED[WIDTH[next(iter(kinds))]]


def variants(source, name):
    got = _scan(source, name)
    if not got or not got[0]:
        return []
    found, clean = got
    regions = {var: info[2] for var, info in found.items()}
    groups = {}
    for var, (kind, *_rest) in found.items():
        groups.setdefault(WIDTH[kind], []).append(var)
    result = []
    for names in groups.values():
        every = [r for v in names for r in regions[v]]
        if len(names) < 2 or any(_overlap(a, b) for i, a in enumerate(every) for b in every[i + 1:]):
            continue
        order = sorted(names, key=lambda v: found[v][1][0])
        survivors = [order[0], max(order, key=lambda v: (len(regions[v]), -order.index(v)))]
        for survivor in dict.fromkeys(survivors):
            edits = []
            for other in names:
                if other != survivor:
                    edits += [e for region in regions[other] for e in _rename(region, survivor)]
                    edits.append((found[other][1][0], found[other][1][1], ''))
            wanted = _widest(found, names)
            if wanted != found[survivor][0]:
                line = re.match(r'[ \t]*', clean[found[survivor][1][0]:]).group()
                edits.append((found[survivor][1][0], found[survivor][1][1], f'{line}{wanted} {survivor};\n'))
            text = _apply(source, edits)
            if text != source and (FAMILY, text) not in result:
                result.append((FAMILY, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
