"""A difference squared for the last time, written as the local multiplied in place: `dx *= dx; ... dx`.

A distance test written `f(((u32) (dx * dx) >> 12) + ((u32) (dy * dy) >> 12))` squares each difference into a fresh
temporary. When the source updated the locals first (`dx *= dx; dy *= dy;`) the squares are the locals' own values, and
the allocator ties the second one to the argument register it is passed in: on a 214-instruction N64 collision handler
(SN GCC 2.8.1 -O2) the last seven register rows went with it, 35 -> 0.

`variants` takes the statements (or `if` conditions) holding `(v * v)` where `v` is a plain integer local that is not
named again after the statement, writes `v *= v;` before it and `v` in place of the product. One child with every such
local of the statement, then one per local. A candidate rewrite; the judge decides.

A second shape is a local that already holds the difference and is assigned its own shifted square,
`dx = (u32) (dx * dx) >> 12;`, written `dx *= dx; dx >>= 12;`. Written as one statement the product takes a register
of its own before the shift; the two updates keep it in the local's. On a 204-instruction N64 collision handler (SN
GCC 2.8.1 `-G0 -mips3 -O2`) both distances at once took 865 -> 595. All such statements together first, then each.
A signed local keeps the logical shift as `dx = (u32) dx >> 12;`.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'square_in_place'
FAMILIES = (FAMILY,)
LIMIT = 8

_SQUARE = re.compile(r'\(\s*([A-Za-z_]\w*)\s*\*\s*\1\s*\)')
# a whole line that starts a statement: a plain one, or an `if` with its condition on that line
_LINE = re.compile(r'(?m)^([ \t]*)((?:if[ \t]*\()?[^{}\n]*(?:;|\{))[ \t]*$')


def _in_loop(clean, lo, position):
    """Whether a `for`, `while` or `do` block encloses `position`."""
    opened = []
    for index in range(lo, position):
        if clean[index] == '{':
            opened.append(index)
        elif clean[index] == '}' and opened:
            opened.pop()
    return any(re.search(r'\b(?:do|(?:for|while)\s*\([^{}]*\))\s*$', clean[max(lo, at - 200):at]) for at in opened)


def _jumps_back(clean, lo, hi, position):
    """Whether a `goto` after `position` names a label before it."""
    return any(re.search(rf'(?m)^[ \t]*{label}[ \t]*:', clean[lo:position])
               for label in re.findall(r'\bgoto\s+(\w+)', clean[position:hi]))


_SHIFTED = re.compile(r'(?m)^([ \t]*)([A-Za-z_]\w*)[ \t]*=[ \t]*(\([ \t]*u32[ \t]*\)[ \t]*)?'
                      r'\([ \t]*\2[ \t]*\*[ \t]*\2[ \t]*\)[ \t]*>>[ \t]*(0[xX][0-9a-fA-F]+|[0-9]+)[ \t]*;[ \t]*$')


def _shifted(source, clean, lo, hi):
    """`v = (u32) (v * v) >> k;` as `v *= v; v >>= k;`: every site together, then each."""
    edits = []
    for found in _SHIFTED.finditer(clean, lo, hi):
        indent, var, cast, shift = found.groups()
        declared = re.search(rf'(?m)^[ \t]*(s32|u32|int|long)\s+{var}\s*;', clean[lo:hi])
        if not declared:
            continue
        # `v >>= k` on a signed local would turn the cast product's logical shift into an arithmetic one
        tail = f'{var} >>= {shift};' if declared.group(1) == 'u32' or not cast else f'{var} = (u32) {var} >> {shift};'
        edits.append((found.start(), found.end(), f'{indent}{var} *= {var};\n{indent}{tail}'))
    groups = ([edits] if len(edits) > 1 else []) + [[one] for one in edits]
    return [(FAMILY, edit(source, group)) for group in groups[:LIMIT]]


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    if re.search(r'\bvolatile\b', clean[lo:hi]):
        return []
    out = _shifted(source, clean, lo, hi)
    for line in _LINE.finditer(clean, lo, hi):
        text = line.group(2)
        # a loop around the statement, or a jump back from below it, could read the squared local again
        if text.startswith(('else', 'for', 'while')) or _in_loop(clean, lo, line.start()) or \
                _jumps_back(clean, lo, hi, line.start()):
            continue
        sites = {}
        for found in _SQUARE.finditer(text):
            sites.setdefault(found.group(1), []).append(found)
        chosen = []
        for var, found in sites.items():
            if not re.search(rf'(?m)^[ \t]*(?:s32|u32|int|long)\s+{var}\s*;', clean[lo:hi]):
                continue
            rest = _SQUARE.sub(lambda m, v=var: '' if m.group(1) == v else m.group(0), text)
            if re.search(rf'\b{var}\b', rest) or re.search(rf'\b{var}\b', clean[line.end():hi]):
                continue
            chosen.append(var)
        groups = ([chosen] if len(chosen) > 1 else []) + [[var] for var in chosen]
        for group in groups:
            start = line.start(2)
            edits = [(line.start(), line.start(), ''.join(f'{line.group(1)}{var} *= {var};\n' for var in group))]
            edits.extend((start + m.start(), start + m.end(), var) for var in group for m in sites[var])
            out.append((FAMILY, edit(source, edits)))
            if len(out) >= LIMIT:
                return out[:LIMIT]
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
