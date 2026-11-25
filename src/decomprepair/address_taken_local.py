"""A scalar local the target keeps in its frame slot: its address taken (`(void)&dsdx;`), so it never gets a register.

GCC 2.x (stmt.c `expand_decl`, `mark_addressable`) gives a scalar local a pseudo only while nothing takes its address; an
addressable one lives in a stack slot for the whole function. The difference shows in a loop's preheader: a value in a
pseudo that crosses calls and gets no saved register is spilled, and reload reads the spill slot wherever the value is
used, but cse knows nothing about a spill. A frame variable is memory to cse: a read of it before a `switch` (or an `if`)
is a fresh load whose register cse follows into the first arm only, so that arm reads the register, the later arm reads
the slot again, and the pseudos of the other locals are numbered and ranked without it.

An N64 texture-strip blitter (SN GCC 2.8.1, `-G0 -mips3 -O2`, 477 instructions) computed a scale step at the top
(`dsdx = (w << 10) / (x1 - x0 + 1);`, stored at once with `sw $t8, 0x24($sp)`), loaded it into the saved register of a
parameter that had just died (`lw $fp, 0x24($sp)`) right before the `beq` of its `switch`, used that register in the first
arm and read `0x24($sp)` again in the second arm's preheader. With `dsdx` a plain local every arrangement kept it in the
spill slot of a pseudo and the saved registers rotated (5142); `(void)&dsdx;` before its assignment gave the target's
slot, the load before the dispatch and a frame one saved register shorter in two other locals (5142 -> 2132), and every
later step of the match was taken from there; on the function's best source the same edit is worth 4602 -> 1125. `volatile` and a one-element array were measured too and are worse: a
volatile read is never hoisted out of the second arm's loop, and an array is not read through a register at all
(6850 and 4602). `(void)&x;` emits no code; it is scaffolding standing in for whatever took the address in the original
(a debug call compiled out, a helper that was inlined away), and polishing may remove it once the match is recorded.
That cse's knowledge of a frame read stops at the first arm is the reading of the measured output, not confirmed in the
compiler source.

`variants` offers, for each plain scalar local (no pointer, array or initialiser) that is assigned exactly once by a
plain `=` and read at least twice, and whose address the function does not already take, the source with `(void)&x;`
inserted before that assignment; then the same for every such local at once. The judge decides; no child is a verdict."""
import re

from .integer_repair_support import edit, view
from .local_weight_ladder import _declaration, units

FAMILY = 'address_taken_local'
FAMILIES = (FAMILY,)
LIMIT = 12


def _scalars(source, name):
    """The names of the function's plain scalar locals (no pointer, no initialiser), in declaration order."""
    part = view(source, name)
    found = []
    if not part:
        return found
    for text in part.clean[part.opening + 1:part.end].split('\n'):
        match = _declaration(text)
        if match and '*' not in match['gap'] and not match['init'] and '[' not in text:
            found.append(match['name'])
    return found


def _assignment(local):
    return re.compile(rf'(?<![\w.>]){re.escape(local)}\s*=(?!=)')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening + 1:part.end]
    found, _ = units(source, name)
    edits, result, seen = [], [], set()

    def add(text):
        if text != source and text not in seen:
            seen.add(text)
            result.append((FAMILY, text))

    for local in _scalars(source, name):
        mention = re.compile(rf'(?<![\w.>]){re.escape(local)}\b')
        if re.search(rf'&\s*{re.escape(local)}\b', body):
            continue
        if re.search(rf'(?<![\w.>]){re.escape(local)}\s*(?:[-+*/%&|^]|<<|>>)=|(?:\+\+|--)\s*{re.escape(local)}\b'
                     rf'|(?<![\w.>]){re.escape(local)}\s*(?:\+\+|--)', body):
            continue
        sets = [(start, end, text) for start, end, text, counts in found
                if counts.get(local) and _assignment(local).match(text.strip())]
        if len(sets) != 1 or len(_assignment(local).findall(body)) != 1:
            continue
        if len(mention.findall(body)) < 4:  # the declaration, the assignment and at least two reads
            continue
        start, end, text = sets[0]
        line_start = source.rfind('\n', 0, start) + 1
        indent = re.match(r'[ \t]*', source[line_start:start])[0]
        change = (start, end, f'(void)&{local};\n{indent}{text}')
        edits.append(change)
        add(edit(source, [change]))
        if len(result) >= LIMIT:
            return result
    if len(edits) > 1:
        add(edit(source, edits))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 93,
          'lanes': ('beam', 'local')}  # the registry: no caller wiring (registry.py)
