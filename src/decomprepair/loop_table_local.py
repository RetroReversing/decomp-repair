"""A global array a loop indexes, held in a pointer local assigned just before the loop.

SN64 GCC 2.8.1 (`-G0 -mips3 -O2 -mgas -meb -mcpu=VR4300 -mhard-float -mfp32`), a 144-instruction N64 text-scrolling
screen walking a table of string pointers: the loop passed `Lines[i]` to its calls and `Lines[0]` to one of them.
Written with the array's name, the table's address stayed split (`lui $s6` in the preheader, `lw $a0, %lo(Lines)($s6)`
at the use) and the induction pointer was built from a second `addiu`. The target had the whole address in a saved
register (`addiu $s6, $v0, %lo(Lines)`), the induction pointer copied from it (`move $s2, $s6`) and `lw $a0, 0($s6)`.
A pointer local holding the array and indexed for every use gave that exactly (1595 -> 515 alone).

    i = 0;                                   i = 0;
    while (test(Lines[i])) {          ->     table = Lines;
        draw(Lines[0]);                      while (test(table[i])) {
                                                 draw(table[0]);

Offered for a one-dimension `extern T NAME[]` the function uses only as `NAME[...]`, at least twice from the first loop
that indexes it with something other than a literal: one child per array, then one with every such array.
"""
import re

from .csource import _blank, find
from .integer_repair_support import edit
from .loop_address_hoist_repairs import _loops
from .pattern_repairs import close

FAMILY = 'loop_table_local'
FAMILIES = (FAMILY,)
LIMIT = 4

_IDENT = r'[A-Za-z_]\w*'
_ARRAY = re.compile(r'\bextern\b[^;(){}=]*?\b(' + _IDENT + r')\s*\[[^\[\];]*\]\s*;')
_LITERAL = re.compile(r'\s*(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*\s*\]')


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    declared = [m[1] for text in (clean[:span[0]], _blank(header or '')) for m in _ARRAY.finditer(text)]
    loops = sorted(_loops(clean, opening, end))
    used = set(re.findall(_IDENT, clean + '\n' + (header or '')))
    found = []
    for array in dict.fromkeys(declared):
        uses = [opening + m.start() for m in re.finditer(rf'(?<![\w.>]){array}\b', body)]
        if len(uses) < 2:
            continue
        subscripts = []
        for at in uses:
            m = re.compile(rf'{array}\s*\[').match(clean, at)
            if not m:
                break  # passed whole, address taken or redeclared: leave it
            subscripts.append(m.end())
        if len(subscripts) != len(uses):
            continue
        if re.search(rf'(?:^|(?<=[;{{}}]))\s*(?:{_IDENT}[\s*]+)+{array}\s*\[[^\]]*\]\s*[;=]', body):
            continue  # a local array of that name
        indexed = [at for at, after in zip(uses, subscripts) if not _LITERAL.match(clean, after)]
        loop = next((a for a, b in loops if any(a <= at < b for at in indexed)), None)
        if loop is None or not clean[:loop].rstrip().endswith((';', '{', '}')):
            continue
        replaced = [at for at in uses if at >= loop]
        if len(replaced) < 2:
            continue
        found.append((array, loop, replaced))

    def apply(chosen):
        names, changes, declarations, settings = set(used), [], [], {}
        for array, loop, replaced in chosen:
            local, n = 'table', 2
            while local in names:
                local, n = f'table{n}', n + 1
            names.add(local)
            declarations.append(f'\n    __typeof__({array}[0]) *{local};')
            settings.setdefault(loop, []).append(f'{local} = {array};')
            changes += [(at, at + len(array), local) for at in replaced]
        for loop, lines in settings.items():
            line = source.rfind('\n', 0, loop) + 1
            indent = re.match(r'[ \t]*', source[line:])[0]
            changes.append((loop, loop, ''.join(f'{text}\n{indent}' for text in lines)))
        changes.append((opening + 1, opening + 1, ''.join(declarations)))
        return FAMILY, edit(source, sorted(changes))

    results = [apply([item]) for item in found[:LIMIT - 1]]
    if len(found) > 1:
        results.append(apply(found))
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
