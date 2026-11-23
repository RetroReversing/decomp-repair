"""A fill loop's `A[i] = v; i++;` written as the cursor the game stepped: `{ T *p = A; do { *p++ = v; i++; } ... }`.

A byte table cleared or filled one element a pass (`D_80108FA0[i] = 0; i++;`, the loop ending on `(i >> bits) == 0`) is
`sb $zero, 0($v1); addiu $a3, $a3, 1; ...; addiu $v1, $v1, 1` in the target: one pointer, set once with a `lui`/`addiu`,
stepped in the delay slot, where the indexed form leaves GCC 2.7.2 a `lui $at; addu $at, $at, $a1; sb ..., %lo(A)($at)`
per element (the symbol cannot be hoisted out of the store's own address). It is the reverse of `table_cursor_index`,
which folds an m2c cursor into the counter; a table the game filled through a pointer is not always the counter's
index, and this is the shape to try when the target has the cursor.

Offered for a loop whose body, at its own level, has exactly one store `A[i] = E;` to an array the source or header
declares (`extern T A[...];`) and exactly one step `i++;` of the counter, where `A` is read and written nowhere else in
the loop and `E` does not read `i`. The cursor starts at `A + i` (at `A` when the counter's last write before the loop
is `i = 0;`: on a path that skips that write the two differ, which is the reviewer's to check), lives in a block of its own around the loop, and is not used after it.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .invariant_shift_local import _loops
from .lockstep_cursor_index import _depths, _steps, _writes

FAMILY = 'array_index_cursor'
FAMILIES = (FAMILY,)


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    context = clean + '\n' + re.sub(r'/\*.*?\*/|//[^\n]*', ' ', header or '', flags=re.S)
    out = []
    for start, opening, closing, stop in _loops(clean, part.opening + 1, part.end):
        body = clean[opening + 1:closing]
        depths = _depths(body)
        for hit in re.finditer(rf'(?<![\w.])(?P<a>{IDENT})\s*\[\s*(?P<i>{IDENT})\s*\]\s*=(?!=)\s*(?P<e>[^;{{}}]+?)\s*;', body):
            if depths[hit.start()] != 0:
                continue
            array, counter, value = hit['a'], hit['i'], hit['e']
            if re.search(rf'\b{counter}\b', value) or re.search(rf'\b{array}\b', value):
                continue
            declared = re.search(rf'\bextern\s+(?:const\s+)?(?P<t>(?:unsigned\s+)?\w+)\s+{array}\s*\[', context)
            if not declared or len(re.findall(rf'\b{array}\b', clean[start:stop])) != 1:
                continue
            steps = _steps(clean, opening + 1, closing, counter)
            if len(steps) != 1 or steps[0][2] != '1' or len(_writes(clean[start:stop], counter)) != 1:
                continue
            word = 'cursor'
            while re.search(rf'\b{word}\b', context):
                word += '_'
            writes = list(re.finditer(rf'(?<![\w+*]){counter}\s*(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=))',
                                      clean[part.opening:start]))
            zero = writes and re.match(rf'{counter}\s*=\s*0\s*;', clean[part.opening + writes[-1].start():])
            origin = array if zero else f'{array} + {counter}'
            at = opening + 1 + hit.start()
            end = opening + 1 + hit.end()
            semicolon = re.match(r'\s*;', clean[stop:])
            finish = stop + (semicolon.end() if semicolon else 0)
            replaced = edit(source, [(at, end, f'*{word}++ = {value};'),
                                     (start, start, f'{{ {declared["t"]} *{word} = {origin}; '),
                                     (finish, finish, ' }')])
            out.append((FAMILY, replaced))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
