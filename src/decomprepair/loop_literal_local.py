"""A literal a call-free loop stores, held in a local set above the loop's own initialisations.

loop.c lifts the `li $v1, -1` of `*(p + 0xF80) = -1;` out of the loop and emits it right before the loop, after the
counter's and the pointer's initialisations; the target had it first (`addiu $v1,$zero,-1; addiu $s1,$zero,0xf;
addiu $v0,$s2,0x3c`), and the scheduler keeps the order of instructions that do not depend on each other. A local set to the
literal above the initialisations stays where it is set (cse keeps a constant that was assigned to a variable; the skill's
note "constant locals stay where they are set"), and the store reads the local: 185 -> 165 with the two initialisations
swapped as well, on a 384-instruction function (isolated judge; no other family offered a child that moved that score).

For a `do` loop with no call and a store of a nonzero literal in its body, preceded by one to three plain assignment
statements, the child sets `V = literal;` above the first of them and stores `V`; a second child swaps the last two
initialisations as well, since neither is better alone. Proposals only; the compiler and the byte judge decide."""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT, edit
from .loop_address_hoist_repairs import _loops
from .pattern_repairs import close

FAMILY = 'loop_literal_local'
FAMILIES = (FAMILY,)
LITERAL = r'-?(?:0[xX][0-9a-fA-F]+|\d+)'
STORE = re.compile(rf'(?P<lhs>\*[^;{{}}=]+?)=(?!=)\s*(?P<lit>{LITERAL})\s*;')
SIMPLE = re.compile(rf'[ \t]*{IDENT}\s*=(?!=)\s*[^;{{}}()]*(?:\([^;{{}}]*\)[^;{{}}()]*)*;[ \t]*\n')
LIMIT = 4


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    end = close(clean, opening, '{', '}') or span[1]
    if re.search(r'\b(?:asm|__asm__)\b|^\s*#', clean[opening:end], re.M):
        return []
    result = []
    for loop in _loops(clean, opening, end):
        text = clean[loop[0]:loop[1]]
        if not text.startswith('do') or re.search(rf'\b(?!(?:if|while|for|switch|return|sizeof|do|else)\b){IDENT}\s*\(', text[2:]):
            continue
        stores = [m for m in STORE.finditer(text) if int(m['lit'], 0) != 0]
        literals = {m['lit'] for m in stores}
        if len(stores) != 1 or len(literals) != 1:
            continue
        store = stores[0]
        line = source.rfind('\n', 0, loop[0]) + 1
        if source[line:loop[0]].strip():
            continue
        # one to three plain assignment statements, one per line, right above the loop
        starts, at = [], line
        for _ in range(3):
            previous = source.rfind('\n', 0, at - 1) + 1
            if at <= 0 or not SIMPLE.fullmatch(clean[previous:at]):
                break
            starts.append(previous)
            at = previous
        if not starts:
            continue
        first = starts[-1]
        indent = re.match(r'[ \t]*', source[first:]).group()
        local = f'lit_{abs(int(store["lit"], 0)):X}' if int(store['lit'], 0) >= 0 else f'neg_{abs(int(store["lit"], 0)):X}'
        if re.search(rf'\b{local}\b', source):
            continue
        decl = re.search(rf'(?m)^([ \t]*)(?:s32|int|long)[ \t]+{IDENT}[ \t]*;[ \t]*\n', source[opening:end])
        if not decl:
            continue
        at_decl = opening + decl.end()
        lit_at = loop[0] + store.start('lit')
        edits = [(first, first, f'{indent}{local} = {store["lit"]};\n'), (lit_at, lit_at + len(store['lit']), local),
                 (at_decl, at_decl, f'{decl[1]}s32 {local};\n')]
        result.append((FAMILY, edit(source, edits)))
        if len(starts) >= 2:
            a, b = starts[1], starts[0]
            one, two = source[a:b], source[b:line]
            swapped = [(first, first, f'{indent}{local} = {store["lit"]};\n'), (a, line, two + one),
                       (lit_at, lit_at + len(store['lit']), local), (at_decl, at_decl, f'{decl[1]}s32 {local};\n')]
            result.append((FAMILY, edit(source, swapped)))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
