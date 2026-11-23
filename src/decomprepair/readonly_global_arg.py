"""A global word the function only passes to calls, declared read-only.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) probe handler, 180 -> 60 on the exact judge. Its three display
calls pass the same global word as the second argument. At `-O2` the argument load is copied into a pseudo when the
call's arguments are set up (`calls.c`, `precompute_register_parameters`: a MEM costs more than 2), and in a loop with
calls loop.c replaces that pseudo by its source only when the load is invariant, which a load is when its MEM is
`RTX_UNCHANGING_P` (a `const` object). The substituted load is one `(set (reg a1) (mem))` in argument order, where the
pseudo's `lui`/`lw` chain was scheduled behind the other argument moves.

readonly_global_arg
    `extern s32 G;` becomes `extern const s32 G;` for an `extern` integer word declared in this source (a header's
    declaration is not rewritten) that a plain call statement of the function passes as an argument and that the function
    never assigns, increments or takes the address of. One child per such word and one with all of them when there are
    two or more. Only the declaration's qualifier changes, so the program's behaviour is the same; whether the original
    object was read-only is not known, and the exact judge decides every child.
"""
import re

from .call_global_stage import plain_calls
from .integer_repair_support import IDENT, INTEGER, edit, view

FAMILY = 'readonly_global_arg'
FAMILIES = (FAMILY,)
LIMIT = 4
_EXTERN = re.compile(rf'\bextern\s+(?P<type>{INTEGER})\s+(?P<name>{IDENT})\s*;')


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    declared = {}
    for hit in _EXTERN.finditer(source):
        if not re.search(rf'\b(?:const|volatile)\s+{INTEGER}\s+{re.escape(hit["name"])}\b', source):
            declared.setdefault(hit['name'], hit)
    if not declared:
        return []
    passed = []
    for _, _, _, spans in plain_calls(part):
        for a, b in spans:
            word = re.fullmatch(rf'\s*({IDENT})\s*', part.clean[a:b])
            if word and word[1] in declared and word[1] not in passed:
                passed.append(word[1])
    words = []
    for word in passed:
        write = rf'(?<![\w.>])(?:\+\+|--)?\s*{word}\s*(?:=(?!=)|[-+*/%&|^]=|<<=|>>=|\+\+|--)|(?:\+\+|--)\s*{word}\b|&\s*{word}\b'
        if not re.search(write, part.clean[part.opening:part.end]):
            words.append(word)
    words = words[:LIMIT]

    def make(chosen):
        return edit(source, [(declared[w].start(), declared[w].end(), f'extern const {declared[w]["type"]} {w};') for w in chosen])

    children = [(FAMILY, make([w])) for w in words]
    if len(words) > 1:
        children.append((FAMILY, make(words)))
    return children


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
