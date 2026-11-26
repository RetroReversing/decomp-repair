"""Block-scoped temporaries of several switch arms, `case 2: { Gfx *g = gfx++; ... }`, written as one function-level local.

m2c and hand rewrites give each display-list arm its own block and pointer (`{ Gfx *_g = gfx++; _g->w0 = ...; }`). A
block's pointer is a pseudo that lives in one basic block, so local-alloc gives it the first register its block leaves
free; one variable that several arms assign is a single pseudo with a life in each of them, which global.c colours
before local-alloc runs, and that takes a register first and moves every temporary of the arm after it. Which arms
shared the variable decides the arms' tails too: two arms whose tails end in the same registers are cross-jumped (the
earlier arm `j`s into the later one's tail). An SN GCC 2.8.1 model loader (sn-n64-281, 618 instructions), its two
`gSPModifyVertex` arms sharing one pointer: 1335 -> 825 (1285 -> 775 under `-mfp32`), the first arm now jumping into the
second's tail as in the target; every arm's block sharing it was worse (1030). Which arms the game shared is read from
the measured scores, not proven: each grouping is its own child.

`variants` finds blocks that open with a declaration `T *x = E;` (or an integer `T x = E;`), groups them by type and
name, and when the name is used nowhere else in the function and never has its address taken, writes `T *x;` at the top
of the function and `x = E;` in the chosen blocks: the whole group, then each pair of neighbouring blocks of it.
"""
import re

from . import c_scan
from .integer_repair_support import IDENT, INTEGER, _address_taken, edit, view

FAMILY = 'block_local_share'
FAMILIES = (FAMILY,)
LIMIT = 12
DECL = re.compile(
    rf'{{(?P<space>\s*)(?P<type>(?:(?:const|volatile|struct|union|unsigned|signed)\s+)*{IDENT})\s*'
    rf'(?P<stars>\*[\s*]*)?(?P<name>{IDENT})\s*=\s*(?P<init>[^;{{}}]+);')


def _blocks(part):
    """Every block-opening declaration with its block's span: (match, block end)."""
    found = []
    for hit in DECL.finditer(part.clean, part.opening + 1, part.end - 1):
        if not hit['stars'] and not re.fullmatch(INTEGER, hit['type']):
            continue
        end = c_scan.close(part.clean, hit.start())
        if end > 0:
            found.append((hit, end))
    return found


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    groups = {}
    for hit, end in _blocks(part):
        stars = re.sub(r'\s', '', hit['stars'] or '')
        groups.setdefault((hit['type'], stars, hit['name']), []).append((hit, end))
    clean, results = part.clean, []
    top = part.opening + 1
    indent = re.match(r'\n?([ \t]*)', clean[top:part.end]).group(1) or '    '
    for (kind, stars, var), blocks in groups.items():
        if len(blocks) < 2 or _address_taken(part.body, var):
            continue
        inside = [(hit.start(), end) for hit, end in blocks]
        outside = [use.start() for use in re.finditer(rf'\b{var}\b', clean[:part.end]) if use.start() > part.opening
                   and not any(lo < use.start() < hi for lo, hi in inside)]
        if outside or re.search(rf'\b{var}\b', clean[:part.opening]):
            continue
        choices = ([blocks] if len(blocks) > 2 else []) + [blocks[i:i + 2] for i in range(len(blocks) - 1)]
        for chosen in choices:
            edits = [(top, top, f'\n{indent}{kind} {stars}{var};')]
            edits += [(hit.start('type'), hit.start('name'), '') for hit, _ in chosen]
            text = edit(source, tuple(edits))
            if text != source and (FAMILY, text) not in results:
                results.append((FAMILY, text))
            if len(results) >= LIMIT:
                return results
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 700}  # the registry: no caller wiring (registry.py)
