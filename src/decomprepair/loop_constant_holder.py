"""A literal a loop compares twice, held in a counter the function is done with, set before the loop's invariant pointers.

loop.c hoists what a loop reads that never changes (a symbol's address, a literal in a compare) into saved registers in
front of the loop, in the order the pseudos were created, and global.c then colours them by
`floor_log2 (refs) * refs / live length` (references weighted by loop depth). A literal `3` in two compares and three
invariant pointers have the same references and almost the same lives, so the pointers' order decides who gets which
register and the literal is emitted after them. The original reused a variable: the counter of an earlier loop, finished,
was set to the literal in front of the pointers (`n = 3;`). Then the literal is the counter's pseudo, whose references
from the earlier loop make it the highest priority (it took `$s1`, the pointers `$s4`/`$s5`/`$fp` in the order the target has),
and it is the first of the hoisted sets (a 445-instruction N64 target picker, KMC gcc 2.7.2, `-G0 -mips3 -mgp32 -mfp32
-O2`: 655 -> 0 together with the order of the pointers; neither alone).

For a block that starts with two or more pointer locals initialised from symbols and holds a loop with an integer literal
(2 or more) compared by `==`/`!=` at least twice, and for each integer local that is not mentioned in the block and not
mentioned after it (or next assigned), offers the pointers declared bare, then `local = K;`, then the pointers assigned
(in each order), with the loop's compares through the local. A candidate for the exact judge, never a verdict.
"""
import itertools
import re

from .integer_repair_support import IDENT, edit, locals_for, view
from .pattern_repairs import close

FAMILY = 'loop_constant_holder'
FAMILIES = (FAMILY,)
LIMIT = 12
WIDTH = {'s32', 'u32', 'int', 'unsigned int', 'unsigned', 's16', 'u16', 's8', 'u8'}
_POINTER = re.compile(rf'(?m)^([ \t]*)((?:{IDENT}[ \t]+)*{IDENT}[ \t]*\*+)[ \t]*({IDENT})[ \t]*=[ \t]*({IDENT})[ \t]*;[ \t]*\n')
_LOOP = re.compile(r'\b(?:do|while|for)\b')
_COMPARE = re.compile(r'(?:==|!=)\s*(0[xX][0-9a-fA-F]+|\d+)\b')


def _assigns(text, name):
    return re.match(rf'\s*{re.escape(name)}\s*=(?!=)', text) is not None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    decls = [d for d in locals_for(part) if ' '.join(d['type'].split()) in WIDTH]
    result = []
    for brace in re.finditer(r'\{', clean[part.opening + 1:part.end]):
        start = part.opening + 1 + brace.end()
        first = _POINTER.match(clean, clean.find('\n', start - 1) + 1)
        pointers, pos = [], first.start() if first else None
        while pos is not None and (hit := _POINTER.match(clean, pos)):
            pointers.append(hit)
            pos = hit.end()
        if len(pointers) < 2:
            continue
        end = close(clean, start - 1, '{', '}')
        loop = _LOOP.search(clean, pos, end) if end else None
        if not loop:
            continue
        counts = {}
        for compare in _COMPARE.finditer(clean, loop.start(), end):
            counts.setdefault(compare[1], []).append(compare)
        constants = [value for value, hits in counts.items() if len(hits) >= 2 and int(value, 0) >= 2][:2]
        nearest = sorted(decls, key=lambda d: -max((m.start() for m in re.finditer(rf'\b{re.escape(d["name"])}\b', clean[:start])), default=-1))
        for value, decl in itertools.product(constants, nearest):
            held = decl['name']
            if not re.search(rf'\b{re.escape(held)}\b', clean[part.opening:start]) or re.search(rf'\b{re.escape(held)}\b', clean[start:end]):
                continue
            later = re.search(rf'\b{re.escape(held)}\b[^;]*', clean[end:part.end])
            if later and not _assigns(later[0], held):
                continue
            indent = pointers[0][1]
            bare = ''.join(f'{p[1]}{p[2].rstrip()}{p[3]};\n' for p in pointers)
            for order in itertools.islice(itertools.permutations(range(len(pointers))), 6):
                assigns = ''.join(f'{pointers[i][1]}{pointers[i][3]} = {pointers[i][4]};\n' for i in order)
                edits = [(pointers[0].start(), pos, f'{bare}{indent}{held} = {value};\n{assigns}')]
                for compare in counts[value]:
                    edits.append((compare.start(1), compare.end(1), held))
                result.append((FAMILY, edit(source, edits)))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 100}  # the registry: no caller wiring (registry.py)
