"""A loop counter's one-off multiple, written as a local set at the top of the loop body.

    do { ... *(u16 *)((u8 *)&table + i * 8) ... i += 1; } while (i < n);

is how m2c writes a table read whose stride only one statement uses. loop.c strength-reduces `sym + i * 8` as a whole,
so the reduced value starts at the symbol's address; the game's loop kept `i * 8` as a value of its own (`s32 i8 = i *
8;`), which the loop pass reduces on its own: the new register starts at 0 and steps by 8 (`sw $zero, 0x2c($sp)` where
the folded form had `lui; addiu; sw`), and the symbol's address is added where it is read (`lui $s2,%hi(table); addu
$s2,$s2,$t8; lhu`) instead of being shared through a register with the other read of the same table (a 417-instruction
input handler: with the folded form the table's address was hoisted into a register and every later register moved,
6575 -> 5445 and the spill slots matched).

Offered for each `COUNTER * K` (K a number above 1) that appears exactly once in the body of a `for` or a `do { } while`
loop that steps COUNTER, when the loop body has no `continue`: a new `s32` local at the top of the body, set from the
product, takes its place. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'loop_scaled_index_local'
FAMILIES = (FAMILY,)
_FOR = re.compile(r'\bfor\s*\(')
_DO = re.compile(r'\bdo\s*\{')


def _loops(clean, start, end):
    """(counter, body_open, body_close) of the `for` and `do { } while` loops in clean[start:end]."""
    for hit in _FOR.finditer(clean, start, end):
        shut = close(clean, hit.end() - 1)
        pieces = clean[hit.end():shut - 1].split(';') if shut else []
        block = re.match(r'\s*\{', clean[shut:]) if shut else None
        if len(pieces) != 3 or not block:
            continue
        init = re.match(rf'\s*(?P<c>{IDENT})\s*=', pieces[0])
        if not init or not re.search(rf'\b{init["c"]}\s*(?:\+\+|\+=\s*1\b)|\+\+\s*{init["c"]}\b', pieces[2]):
            continue
        open_at = shut + block.end() - 1
        yield init['c'], open_at, close(clean, open_at, '{', '}')
    for hit in _DO.finditer(clean, start, end):
        open_at = hit.end() - 1
        shut = close(clean, open_at, '{', '}')
        if not shut or not re.match(r'\s*while\s*\(', clean[shut:]):
            continue
        last = re.search(rf'(?P<c>{IDENT})\s*(?:\+\+|\+=\s*1)\s*;\s*\Z|\+\+\s*(?P<d>{IDENT})\s*;\s*\Z', clean[open_at + 1:shut - 1])
        if last:
            yield last['c'] or last['d'], open_at, shut


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    seen = set()
    for counter, open_at, shut in _loops(clean, part.opening + 1, part.end):
        if not shut or re.search(r'\bcontinue\b', clean[open_at:shut]):
            continue
        body = clean[open_at + 1:shut - 1]
        pattern = re.compile(rf'(?<![\w.>])\b{counter}\s*\*\s*(?P<k>{NUMBER})\b(?!\s*[\w(\[])')
        counts = {}
        for hit in pattern.finditer(body):
            counts.setdefault(hit['k'], []).append(hit)
        for k, hits in counts.items():
            if len(hits) != 1 or int(k, 0) < 2 or (open_at, k) in seen:
                continue
            seen.add((open_at, k))
            local = f'{counter}_x{int(k, 0)}'
            if re.search(rf'\b{local}\b', clean):
                continue
            hit = hits[0]
            at = open_at + 1 + hit.start()
            indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, open_at) + 1:])[0] + '  '
            out.append((FAMILY, edit(source, [
                (open_at + 1, open_at + 1, f'\n{indent}s32 {local} = {counter} * {k};'),
                (at, open_at + 1 + hit.end(), local)])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
