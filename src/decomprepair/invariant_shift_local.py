"""A loop-invariant `1 << n` or `(1 << n) - 1` named once, in the block that opens the loop it is invariant in.

A bit-stream or table-building routine masks with `(1 << bits) - 1` and builds codes with `1 << length` inside its
loops. Written in place, GCC 2.7.2's loop pass moves the shift out as a movable and puts it in the preheader *after*
the strength-reduced address initialisations (and its `li 1` constant with it: a spilled constant is re-made at every
use); written once into a local at the top of the block that holds the loop, the `sllv` comes where the author's own
local would put it: before them, and the local's references get the loop weights the author's did. The mask local is
also a pseudo of its own, which the allocator may spill (`sw` once, `lw` per use) where the in-place spelling kept it
in a register: both are how the target's hoisted values look in the functions measured.

Per expression `(1 << X) - 1` or `1 << X` that sits inside a loop whose body never assigns X (nor takes its address),
this declares `u32 inv_mask = ...;` / `u32 inv_bit = ...;` as the first statement of the block that contains the
outermost such loop, and reads it in the loop. The block's own earlier code must not assign X either (the value is read
at the block's start), and a loop that already reads a local of that value is left alone. Found by hand on a 681-instruction
bit-stream decoder (KMC gcc 2.7.2): `mk = (1 << tb) - 1` before a table-fill loop took 5320 -> 5055, `hb = 1 << c` before
its code-assignment loop 5055 -> 4665 (docs/learnings/function/bit-stream-decoder-table-loops-and-register-roles.md).
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'invariant_shift_local'
FAMILIES = (FAMILY,)

MASK = re.compile(rf'\(\s*1\s*<<\s*(?P<x>{IDENT})\s*\)\s*-\s*1\b')
BIT = re.compile(rf'(?<![\w<])1\s*<<\s*(?P<x>{IDENT})\b')


def _loops(clean, begin, end):
    """(start, body_open, body_close, stop) of every braced loop in [begin, end): the loop's own text is [start, stop)."""
    loops = []
    for hit in re.finditer(r'\bdo\s*\{', clean[begin:end]):
        opening = begin + hit.end() - 1
        closing = close(clean, opening, '{', '}')
        tail = re.match(r'\s*while\s*\(', clean[closing:end]) if closing else None
        if not tail:
            continue
        stop = close(clean, closing + tail.end() - 1, '(', ')')
        if stop:
            loops.append((begin + hit.start(), opening, closing - 1, stop))
    for hit in re.finditer(r'\b(?:while|for)\s*\(', clean[begin:end]):
        opening = begin + hit.end() - 1
        after = close(clean, opening, '(', ')')
        brace = re.match(r'\s*\{', clean[after:end]) if after else None
        if not brace:
            continue
        body = after + brace.end() - 1
        closing = close(clean, body, '{', '}')
        if closing:
            loops.append((begin + hit.start(), body, closing - 1, closing))
    return loops


def _assigned(text, name):
    return bool(re.search(rf'\b{name}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|\b{name}\s*(?:\+\+|--)|(?:\+\+|--)\s*{name}\b'
                          rf'|(?<![&\w])&\s*{name}\b', text))


def _block_open(clean, at, floor):
    """Position of the `{` of the block that contains `at`."""
    depth = 0
    for pos in range(at - 1, floor - 1, -1):
        if clean[pos] == '}':
            depth += 1
        elif clean[pos] == '{':
            if depth == 0:
                return pos
            depth -= 1
    return None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    loops = _loops(clean, part.opening + 1, part.end)
    found = []
    for kind, pattern in (('mask', MASK), ('bit', BIT)):
        seen = set()
        for hit in pattern.finditer(clean, part.opening + 1, part.end):
            x = hit['x']
            text = re.sub(r'\s+', '', hit.group(0))
            if (kind, text) in seen:
                continue
            seen.add((kind, text))
            enclosing = sorted((lp for lp in loops if lp[0] <= hit.start() < lp[3]), key=lambda lp: lp[0])
            chosen = next((lp for lp in enclosing if not _assigned(clean[lp[0]:lp[3]], x)), None)
            if not chosen:
                continue
            opening = _block_open(clean, chosen[0], part.opening)
            if opening is None or _assigned(clean[opening + 1:chosen[0]], x):
                continue
            word = 'inv_' + kind
            while re.search(rf'\b{word}\b', clean):
                word += '_'
            expression = hit.group(0).strip()
            if kind == 'bit':
                expression = f'1 << {x}'
            edits = [(opening + 1, opening + 1, f' u32 {word} = {expression};')]
            count = 0
            for inner in pattern.finditer(clean, chosen[0], chosen[3]):
                if re.sub(r'\s+', '', inner.group(0)) != text:
                    continue
                if kind == 'bit' and MASK.search(clean, max(chosen[0], inner.start() - 1), inner.end() + 8):
                    continue  # the shift inside a mask: the mask is the unit
                start, stop = inner.start(), inner.end()
                before, after = clean[:start].rstrip(), clean[stop:].lstrip()
                if before.endswith('(') and after.startswith(')') and not re.search(r'[\w)\]]\s*$', before[:-1]):
                    start, stop = before.rindex('('), stop + (len(clean[stop:]) - len(after)) + 1
                edits.append((start, stop, word))
                count += 1
            if count:
                found.append((FAMILY, edit(source, edits)))
    return found


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
