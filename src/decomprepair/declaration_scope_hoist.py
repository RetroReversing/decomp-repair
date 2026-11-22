"""A local declared at the start of an inner block, moved to the function's own declarations in `spXX` order.

gcc 2.7.2 numbers pseudo registers in the order it expands declarations: a function-level declaration gets its pseudo
when the function starts, a block-level one when the block is entered, and reload hands out the stack slots of the
spilled pseudos in pseudo-number order, eight bytes each (see `declaration_scope_sink`, the other direction; the notes
in docs/COMPILER_MATCHING_LEARNINGS.md of decompdecomp: "spill slots are numbered by pseudo number").

A 851-instruction N64 ray test (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) kept the pointers its loops need
(the addresses of its scratch vectors) in spilled pseudos named by m2c after their slots (`sp164`, `sp16C`, `sp174`,
...). An earlier search had declared two of them (`sp174`, `sp194`) at the top of the block that uses them, which
numbered them after every other `spXX` local, so the room section's six address slots came out as 0x174, 0x17c, 0x184,
0x1ac, 0x1a4, 0x19c where the target has them in the order of their names, 0x174 to 0x194 and 0x1ac. With both moved
back to the function's declarations, between their neighbours by name, 23 differing rows went away (5943 -> 5920 in
the isolated judge, the 24 `s` rows of the slot offsets among them) and nothing else moved. Hypothesis from the
numbering above and the slots read in the target, not confirmed in the compiler's source.

`declaration_scope_hoist` offers, for each scalar or pointer local declared without an initializer inside an inner
block (not the function's own) whose name is declared nowhere else, the function with that declaration moved to the
function's declarations. The place is the one the names suggest: m2c's `spXX` names are stack offsets, so a local
named `sp174` goes before the first function-level `sp` local with a larger offset, and after the last one otherwise;
a name without an offset goes after the last declaration. One child hoists every such local together, since the slots
only come out right when the whole order is. The judge decides.
"""
import re

from .declaration_scope_sink_repairs import CONTROL, DECLARATION, KEYWORDS, _blocks
from .integer_repair_support import IDENT, edit, view

FAMILY = 'declaration_scope_hoist'
FAMILIES = (FAMILY,)
LIMIT = 6
OFFSET = re.compile(r'^sp([0-9A-Fa-f]+)$')


def _line(clean, match):
    """(start, end) of the whole source line a declaration match sits on, its newline included."""
    start = clean.rfind('\n', 0, match.start('type')) + 1
    end = clean.find('\n', match.end())
    return start, (len(clean) if end < 0 else end + 1)


def _depth(clean, begin, index):
    return clean.count('{', begin, index) - clean.count('}', begin, index)


def _where(top, local):
    """The index in the list of function-level declarations where `local` goes: by stack offset when both have one."""
    mine = OFFSET.match(local['name'])
    last_named = None
    for index, other in enumerate(top):
        theirs = OFFSET.match(other['name'])
        if mine and theirs:
            if int(theirs[1], 16) > int(mine[1], 16):
                return index
            last_named = index
    if mine and last_named is not None:
        return last_named + 1
    return len(top)


def _statement_block(clean, blocks, position):
    """Is the block around `position` a statement block, not the body of a `struct` or `union` declaration?"""
    holders = [block for block in blocks if block[0] < position < block[1]]
    if not holders:
        return False
    opening = max(holders)[0]
    return not re.search(r'\b(?:struct|union|enum)\b[^{};()]*$', clean[max(0, opening - 120):opening])


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    clean = part.clean
    blocks = _blocks(clean, part.opening, part.end)
    outer = [block for block in blocks if block[0] == part.opening]
    if not outer:
        return []
    body_start, body_end = part.opening + 1, outer[0][1]
    top, inner = [], []
    for match in DECLARATION.finditer(clean, body_start, body_end):
        if CONTROL.search(match['type']) or match['type'].strip().split()[-1] in KEYWORDS:
            continue
        before = clean[:match.start('type')].rstrip()[-1:]
        if before not in ('', ';', '{', '}'):
            continue
        depth = _depth(clean, body_start, match.start())
        if depth == 0:
            top.append(match)
        elif _statement_block(clean, blocks, match.start()):
            inner.append(match)
    if not inner or not top:
        return []
    names = re.findall(rf'(?<![\w.>])({IDENT})[\s*]+({IDENT})\s*[;,\[=](?!=)', clean[body_start:body_end])
    seen = {}
    for kind, local in names:
        if kind not in KEYWORDS:
            seen[local] = seen.get(local, 0) + 1
    movable = [match for match in inner
               if seen.get(match['name']) == 1
               and not re.search(rf'&\s*{re.escape(match["name"])}\b', clean[body_start:body_end])]
    if not movable:
        return []
    last_top = max(_line(clean, match)[1] for match in top)

    def moved(chosen):
        # entries: [name, insertion point, text or None]; a top-level declaration stays where it is
        order = [[match['name'], _line(clean, match)[0], None] for match in top]
        edits = []
        for match in sorted(chosen, key=lambda item: item.start()):
            start, end = _line(clean, match)
            edits.append((start, end, ''))
        indent = re.match(r'[ \t]*', source[_line(clean, top[0])[0]:])[0]
        key = lambda item: int(OFFSET.match(item['name'])[1], 16) if OFFSET.match(item['name']) else 1 << 60
        for match in sorted(chosen, key=key):
            index = _where([{'name': entry[0]} for entry in order], match)
            at = order[index][1] if index < len(order) else last_top
            order.insert(index, [match['name'], at, f'{indent}{source[match.start("type"):match.end()].strip()}\n'])
        inserts = {}
        for _, at, text in order:
            if text:
                inserts.setdefault(at, []).append(text)
        for at, lines in inserts.items():
            edits.append((at, at, ''.join(lines)))
        return edit(source, edits)

    found = []
    if len(movable) > 1:
        found.append((FAMILY, moved(movable)))
    for match in movable[:LIMIT]:
        found.append((FAMILY, moved([match])))
    return found
