"""m2c's array of stack words written back as the separate locals the game had: `s32 sp10[34];` -> 34 `s32`s.

When a function has more live `int` locals than registers, the compiler spills them to consecutive stack words, and
m2c reads the run back as one array. An array stays in memory, so the compiler can no longer keep any of it in a
register and orders its loads and stores as memory accesses. Separate locals give the allocator the same words as
spill slots. On the draft of a 511-instruction N64 input sampler (SN64 GCC 2.8.1, `-G0 -mips3 -O2`; 56 flag locals,
34 of them spilled) the narrowed reads of `stack_word_half_read` plus this split took 24715 (the reads alone) to 15355,
below the 15547 best of 25 attempts.

spill_array_scalars
    Every local array named like a stack slot (`sp10`) whose every use is `sp10[constant]` inside its bounds becomes
    `sp10_0 ... sp10_N`, in index order. When the source also reads unassigned `unksp` bytes inside those words,
    `stack_word_half_read` is applied first and the split offered on its result, as one child.
"""
import re

from . import stack_word_half_read
from .integer_repair_support import edit, view

FAMILY = 'spill_array_scalars'
FAMILIES = (FAMILY,)
LIMIT = 128

_DECLARATION = re.compile(r'(?<=[;{}])\s*(?P<type>[su]32|M2C_UNK|int)\s+(?P<name>sp[0-9A-F]+)\s*'
                          r'\[\s*(?P<size>0[xX][0-9a-fA-F]+|\d+)\s*\]\s*;')


def _split(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile)\b', part.body):
        return None
    edits = []
    for hit in _DECLARATION.finditer(part.clean, part.opening, part.end):
        array, size = hit['name'], int(hit['size'], 0)
        if not 2 <= size <= LIMIT or re.search(rf'\b{array}_\d', part.clean):
            continue
        mention = re.compile(rf'\b{array}\b')
        indexed = re.compile(r'\s*\[\s*(0[xX][0-9a-fA-F]+|\d+)\s*\]')
        uses = []
        for use in mention.finditer(part.clean, part.opening, part.end):
            if hit.start('name') == use.start():
                continue
            index = indexed.match(part.clean, use.end())
            before = part.clean[part.opening:use.start()].rstrip()
            if not index or int(index[1], 0) >= size or (before.endswith('&') and not before.endswith('&&')):
                break
            uses.append((use.start(), index.end(), f'{array}_{int(index[1], 0)}'))
        else:
            if uses:
                locals_ = ' '.join(f"{hit['type']} {array}_{index};" for index in range(size))
                edits.append((hit.start('type'), hit.end(), locals_))
                edits.extend(uses)
    return edit(source, edits) if edits else None


def variants(source, name, asm=''):
    out = []
    for _, narrowed in stack_word_half_read.variants(source, name, asm=asm)[:1]:
        split = _split(narrowed, name)
        if split:
            out.append(split)
    plain = _split(source, name)
    if plain and not out:
        out.append(plain)
    return [(FAMILY, text) for text in out]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm')}
