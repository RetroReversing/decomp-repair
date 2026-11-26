"""A pointer local set once to a row of a two-dimensional table, `p = TABLE[i];`, read only as `p[k]`: the reads
written as `TABLE[i][k]`.

A colour interpolator on the N64 (SN64 GCC 2.8.1, `-mfp32`) read a tint row as `u8 *tint = D_800A9480[D_80140148];`
and then `tint[0]`, `tint[1]`, `tint[2]` after nine stores to stack arrays. With the row in a pointer local the nine
stores all wait for the first tint read in the first scheduler (alias analysis keeps a store and a load through the
local's register apart only when it can see the load's base); written as `D_800A9480[D_80140148][k]` at each use, the
block's order and registers moved toward the target's: 2756 -> 2676 under the app's judge with `-mfp32`, and a later
chain of library steps from there reached 2540, where nothing reached from the pointer form went below 2756. Which
alias rule decides it is a hypothesis, not read in the compiler's source.

The rewrite is faithful when the row expression reads the same memory at each use as it did at the assignment: its
names are not written, and no call is made, between the assignment and the last read. Variants: every read inlined
and the local's declaration and assignment removed.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'row_pointer_inline'
FAMILIES = (FAMILY,)

# `p = TABLE[expr];` on a line of its own (the local declared elsewhere), or `T *p = TABLE[expr];`
ASSIGN = re.compile(r'(?m)^[ \t]*(?:(?:const\s+)?[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*\s*\*\s*)?(?P<v>[A-Za-z_]\w*)[ \t]*=[ \t]*'
                    r'(?P<t>[A-Za-z_]\w*)[ \t]*\[(?P<i>[^\[\];{}\n]+)\][ \t]*;[ \t]*\n')
CALL = re.compile(r'\b(?!if\b|while\b|for\b|switch\b|return\b|sizeof\b)[A-Za-z_]\w*\s*\(')


def _declaration(body, var):
    """The span of a declaration line that declares only `var` as a plain pointer, or None."""
    hit = re.search(rf'(?m)^[ \t]*(?:const\s+)?[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*\s*\*\s*{var}[ \t]*;[ \t]*\n', body)
    return hit.span() if hit else None


def _written(text, name):
    return re.search(rf'(?<![\w.>]){name}\s*(?:[-+*/|&^%]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{name}\b|\b{name}\s*(?:\+\+|--)'
                     rf'|&\s*{name}\b', text)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0 or (end := close(clean, opening, '{', '}')) is None:
        return []
    body, clean_body = source[opening:end], clean[opening:end]
    found = []
    for hit in ASSIGN.finditer(clean_body):
        var, table, index = hit['v'], hit['t'], hit['i'].strip()
        if var == table or re.search(r'\w\s*\(|\+\+|--|[^=!<>]=[^=]', index):
            continue
        rest = clean_body[hit.end():]
        reads = list(re.finditer(rf'(?<![\w.>]){var}\b', rest))
        if not reads or _written(rest, var):
            continue
        # every read is `var[k]`
        if any(not re.match(r'\s*\[', rest[r.end():]) for r in reads):
            continue
        last = reads[-1].end()
        between = rest[:last]
        names = set(re.findall(r'[A-Za-z_]\w*', index)) | {table}
        if CALL.search(between) or any(_written(between, n) for n in names):
            continue
        # the local is not read before its assignment
        if re.search(rf'(?<![\w.>]){var}\b(?!\s*;)', re.sub(rf'(?m)^[^\n]*\*\s*{var}\s*;[^\n]*\n', '', clean_body[:hit.start()])):
            continue
        row = f'{table}[{index}]'
        tail = re.sub(rf'(?<![\w.>]){var}(?=\s*\[)', lambda _, w=row: w, body[hit.end():])
        head = body[:hit.start()]
        if body[hit.start():hit.end()].lstrip().startswith(var):  # declared on a line of its own: drop that too
            decl = _declaration(head, var)
            if decl:
                head = head[:decl[0]] + head[decl[1]:]
        text = head + tail
        candidate = source[:opening] + text + source[end:]
        if candidate != source and all(candidate != t for _, t in found):
            found.append((FAMILY, candidate))
    return found


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 140}
