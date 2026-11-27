"""repeated_run_scopes: each copy of a repeated statement run wrapped in its own one-shot `do { } while (0)`.

A source macro that repeats a block (get a slot, spawn an object, set its fields) leaves a loop note after every copy,
and GCC 2.x's cse stops there. Written flat, the copies share their literals: KMC gcc 2.7.2 (`-O1`) kept the three
copies' `0xFFFF`, `0x5B` and `0xFF` in saved registers (a larger frame) where the target loads each again. An N64
effect spawner of 248 instructions, three copies of one run, went 3636 -> 0 with all three wrapped at once; wrapping
one statement at a time (`fence_statement_deep`, `call_one_shot_scope`) reached 3225 and stopped.

A copy starts at a statement with a call that the same block repeats word for word, and runs to the next one (the last
to the block's end). A run holding a declaration, a `break`, a `continue` or a `case` is left alone: the new loop
would take them over."""
import re

from .arm_block_support import brace_pairs, statements
from .integer_repair_support import edit, view

FAMILY = 'repeated_run_scopes'
FAMILIES = (FAMILY,)
LIMIT = 6
CALL = re.compile(r'(?<![\w.])(?!(?:if|while|for|switch|sizeof|return)\b)[A-Za-z_]\w*\s*\(')
UNSAFE = re.compile(r'\b(?:break|continue|case|default)\b|^[ \t]*#', re.M)
DECLARATION = re.compile(r'(?!(?:return|goto|else|do)\b)[A-Za-z_]\w*(?:\s+|\s*\*+\s*)\**\s*[A-Za-z_]\w*\s*(?:[;=,\[]|$)')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    pairs = brace_pairs(clean, part.opening, part.end + 1 if clean[part.end:part.end + 1] == '}' else part.end)
    if not pairs:
        pairs = {part.opening: part.end}
    out, seen = [], set()
    for opening, closing in sorted(pairs.items()):
        spans = statements(clean, opening + 1, closing)
        texts = [' '.join(clean[a:b].split()) for a, b in spans]
        for anchor in dict.fromkeys(texts):
            starts = [i for i, text in enumerate(texts) if text == anchor]
            if len(starts) < 2 or '{' in anchor or not CALL.search(anchor):
                continue
            runs = list(zip(starts, starts[1:] + [len(spans)]))
            if any(UNSAFE.search(clean[spans[a][0]:spans[b - 1][1]])
                   or any(DECLARATION.match(text) for text in texts[a:b]) for a, b in runs):
                continue
            edits = []
            for a, b in runs:
                begin, end = spans[a][0], spans[b - 1][1]
                edits.append((begin, end, 'do {\n' + source[begin:end] + '\n} while (0);'))
            text = edit(source, edits)
            if text not in seen:
                seen.add(text)
                out.append((FAMILY, text))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 96}  # the registry: no caller wiring (registry.py)
