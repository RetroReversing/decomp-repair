"""A byte array's address added to an index inside a nested loop, kept out of GCC 2.7's loop hoisting.

GCC 2.7's loop pass moves a constant address (`lui`/`addiu` of a symbol) out of a loop when the pseudo that holds it
is set once. Every such address that stays in the loop competes for a saved register by floor_log2(uses) * uses /
live length, so a base used once, inside a nested loop's guarded block, is hoisted with the rest and takes the register
(or pushes out a table the game's code did keep in one). The game's code built that base in the block, a plain
`lui`/`addiu` into a scratch register, next to the add. Two things make the compiler leave it there, and both were
needed on one function of a KMC GCC game (135 -> 120 -> 0, see COMPILER_MATCHING_LEARNINGS.md):

    __base = D;  (top of the function)           __base = 0;  (top: the pseudo is now set twice, never hoisted)
    ...  f(x, (i * 0xC) + __base, y);      ->    ...  __index = i * 0xC;
                                                      __base = D;
                                                      f(x, __base + __index, y);

The second set makes the pseudo ineligible for the loop pass. The index is computed before the base is built, which
puts the `lui`/`addiu` after the index arithmetic (the scheduler keeps the order the RTL was made in) and the add
with the index operand first.

Works on the draft's `(X) + D` / `D + (X)` and on the pointer the symbol-address family made (`__base_D`), for a byte
array only (an element wider than a byte scales the index, which this does not model). Offers the two orders of the
assignments, and the form without the zero set.
"""
import re

from .csource import _blank, find
from .loop_address_hoist_repairs import _loops
from .pattern_repairs import close
from .symbol_base_repairs import ARRAY, IDENT, _statement_start

FAMILY = 'loop_symbol_base_block'
FAMILIES = (FAMILY,)
BYTES = ('char', 'u8', 's8')
LIMIT = 6

_INDEX = r'\((?P<x>[^()]*(?:\([^()]*\)[^()]*)*)\)'


def _uses(body, names):
    """(start, end, index text, name, index first) of each `(X) + NAME` / `NAME + (X)`, with X an expression."""
    found = []
    for name in names:
        for m in re.finditer(_INDEX + r'\s*\+\s*(?P<b>' + re.escape(name) + r')\b(?!\s*[\[(])', body):
            found.append((m.start(), m.end(), m['x'], name, True))
        for m in re.finditer(r'(?<![\w.>])(?P<b>' + re.escape(name) + r')\s*\+\s*' + _INDEX, body):
            found.append((m.start(), m.end(), m['x'], name, False))
    return [u for u in sorted(found) if re.search(r'[-+*/<>&|]', u[2])]


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    outside = clean[:span[0]] + clean[span[1]:]
    body = clean[opening:end]
    loops = _loops(body, 0, len(body))
    result = []
    for m in ARRAY.finditer(outside):
        symbol, kind = m['name'], m['type'].split()[-1]
        if kind not in BYTES:
            continue
        local = '__base_' + symbol
        held = re.search(r'(?m)^[ \t]*' + re.escape(local) + r'\s*=\s*' + re.escape(symbol) + r'\s*;[ \t]*\n', body)
        names = [local] if re.search(r'\b' + local + r'\b', body) else [symbol]
        for use in _uses(body, names):
            start, stop, index, base, index_first = use
            if not any(a <= start < b for a, b in loops):
                continue
            if held and not (held.start() < start) and base == local:
                continue
            at = _statement_start(body, start)
            if at >= start:
                continue
            statement = at + len(re.match(r'\s*', body[at:])[0])
            indent = re.match(r'\s*', body[at:])[0].split('\n')[-1] or '    '
            temp = '__index_' + symbol
            if re.search(r'\b' + temp + r'\b', body):
                continue
            for order, zero in (('index', True), ('base', True), ('index', False)):
                text = source
                # edits from the back of the function to the front, so the offsets stay valid
                new_use = f'{local} + {temp}'
                text = text[:opening + start] + new_use + text[opening + stop:]
                lines = [f'{temp} = {index};', f'{local} = {symbol};']
                if order == 'base':
                    lines.reverse()
                text = text[:opening + statement] + ('\n' + indent).join(lines) + '\n' + indent + text[opening + statement:]
                top = opening + 1
                if held:
                    first, last = opening + held.start(), opening + held.end()
                    replacement = f'{local} = 0;\n' if zero else ''
                    text = text[:first] + (re.match(r'[ \t]*', body[held.start():])[0] + replacement if replacement else '') \
                        + text[last:]
                    declared = f'\n    s32 {temp};'
                else:
                    declared = f'\n    u8 *{local};\n    s32 {temp};'
                text = text[:top] + declared + text[top:]
                if not held and zero:
                    # (a statement after the declarations: C89 refuses one before them)
                    block = re.match(r'\{(?:\s*(?:register\s+)?[\w ]+?[\s*]+' + IDENT + r'(?:\s*\[[^]]*\])?\s*;)*',
                                     text[opening:])
                    cut = opening + block.end()
                    text = text[:cut] + f'\n\n    {local} = 0;' + text[cut:]
                if text != source and text not in [t for _, t in result]:
                    result.append((FAMILY, text))
            if len(result) >= LIMIT:
                return result
    return result
