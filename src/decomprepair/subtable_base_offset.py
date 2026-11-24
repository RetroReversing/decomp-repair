"""A two-level table's second lookup with the entry's offset in the pointer: `(T + K)[(e >> 7) + w]` as `(T + K + (e >> 7))[w]`.

A canonical-code decoder looks a peeked window up twice: `e = T[x & 0x3FF]`, and, when the entry says the code is
longer, `T2[(e >> 7) + ((x >> 10) & mask)]`, where the entry's high bits are the subtable's offset. KMC GCC 2.7.2
(`-O2`, N64) folds both spellings to one `addu; sll 1; addu base` sum, but not with the same operands: written as one
index, the sum's first operand is the entry's offset, so local-alloc ties the sum to the offset's register; written with
the offset in the pointer (`(T + K + (e >> 7))[w]`, the subtable's own address and then the index into it), the integer
parts are reassociated with the masked window first (the target's `and $v1,$v1,$v0; addu $v1,$v1,$a0`, the offset
computed before the window by `srl $a0,$t1,7`), and the window's register stays the one it was peeked into.

The window's shift is offered both ways: as written, and, when it is written in place (`(x >>= 10)`, decomp-repair
`last_use_shift_in_place`) and the window is not read again before it is set afresh, as a plain `(x >> 10)`, whose
result is a new temporary that local-alloc gives the window's dying register. On a 681-instruction bit-stream decoder
(two lookups, the literal/length table's in place and the distance table's not) the pointer form at both sites with the
first site's shift written plain moved the whole decode loop onto the target's registers (515 -> 595 alone, the R2 sort
loop's counter then free to take its own role: 415; checked on 600 generated streams against a clean transcription).
Each site alone, both together, and each with its shift plain are offered.

Rewrites `B[A + C]` where `B` is a global array or a parenthesised `(sym + K)` / `(sym - K)`, and `A` is a parenthesised
term (`(e >> 7)`); declines in a function that mentions `volatile`.
"""
import re

from .integer_repair_support import edit, view
from .last_use_shift_in_place import _first_mention_is_assignment, _loops

FAMILY = 'subtable_base_offset'
FAMILIES = (FAMILY,)
LIMIT = 4

_BASE = re.compile(r'(\(\s*[A-Za-z_]\w*\s*[+-]\s*(?:0[xX][0-9a-fA-F]+|\d+)\s*\)|\b[A-Za-z_]\w*)\s*\[')
_STATEMENT = re.compile(r'(?m)^([ \t]*)([^;{}\n][^;{}]*;)')
_IN_PLACE = re.compile(r'\(\s*([A-Za-z_]\w*)\s*>>=\s*(\d+|0[xX][0-9a-fA-F]+)\s*\)')


def _close(text, at, left, right):
    depth = 0
    for i in range(at, len(text)):
        depth += (text[i] == left) - (text[i] == right)
        if depth == 0:
            return i
    return None


def _split_plus(text):
    """The index split at its one top-level `+` after a leading parenthesised term: (first, rest) or None."""
    text = text.strip()
    if not text.startswith('('):
        return None
    shut = _close(text, 0, '(', ')')
    if shut is None:
        return None
    rest = text[shut + 1:].lstrip()
    if not rest.startswith('+'):
        return None
    second = rest[1:].strip()
    depth = 0
    for ch in second:
        depth += (ch == '(') - (ch == ')')
        if depth < 0:
            return None
        if depth == 0 and ch in '+-,?:<>=|^&*/%' and not second.startswith('('):
            return None
    if depth:
        return None
    if second.startswith('(') and _close(second, 0, '(', ')') != len(second) - 1:
        return None  # `(a) + (b) & c`: not one term
    return text[:shut + 1], second


def _plain_shift(index, clean, statement, hi, loops):
    """`index` with its `(V >>= K)` written `(V >> K)` when V's value after the statement is never read; else None."""
    found = list(_IN_PLACE.finditer(index))
    if len(found) != 1:
        return None
    var = found[0].group(1)
    later = clean[statement.end():hi]
    if re.search(rf'\b{var}\b', later) and not _first_mention_is_assignment(later, var):
        return None
    inside = [body for body in loops if body[0] < statement.start() < body[1]]
    if any(not _first_mention_is_assignment(clean[body[0]:body[1]], var) for body in inside):
        return None
    return index[:found[0].start()] + f'({var} >> {found[0].group(2)})' + index[found[0].end():]


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    if re.search(r'\bvolatile\b', clean[lo:hi]):
        return []
    loops = _loops(clean, lo, hi)
    sites = []  # [(plain site, site with its shift written plain or None)]
    for statement in _STATEMENT.finditer(clean, lo, hi):
        text = statement.group(2)
        for base in _BASE.finditer(text):
            if base.start() > 0 and (text[base.start() - 1].isalnum() or text[base.start() - 1] in '_.>'):
                continue
            opening = base.end() - 1
            shut = _close(text, opening, '[', ']')
            if shut is None:
                continue
            split = _split_plus(text[opening + 1:shut])
            if not split:
                continue
            first, rest = split
            if rest.startswith('(') and _close(rest, 0, '(', ')') == len(rest) - 1:
                rest = rest[1:-1].strip()  # `[((x >> 10) & m)]` reads `[(x >> 10) & m]`
            b = base.group(1)
            pointer = f'({b[1:-1].strip()} + {first})' if b.startswith('(') else f'({b} + {first})'
            at = statement.start(2) + base.start()
            end = statement.start(2) + shut + 1
            plain = _plain_shift(rest, clean, statement, hi, loops)
            sites.append(((at, end, f'{pointer}[{rest}]'),
                          (at, end, f'{pointer}[{plain}]') if plain else None))
    sites = sites[:LIMIT]
    out = []
    for site, plain in sites:
        out.append(edit(source, [site]))
        if plain:
            out.append(edit(source, [plain]))
    if len(sites) > 1:
        out.append(edit(source, [site for site, _ in sites]))
        for k, (_, plain) in enumerate(sites):
            if plain:
                out.append(edit(source, [plain if j == k else s for j, (s, _) in enumerate(sites)]))
    seen, result = set(), []
    for text in out:
        if text != source and text not in seen:
            seen.add(text)
            result.append((FAMILY, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
