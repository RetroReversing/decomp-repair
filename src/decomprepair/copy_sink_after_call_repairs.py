"""A pointer copy written before a call, written after it.

m2c places `walk = buffer;` before the call that fills `buffer` and passes it on:

    buffer = alloc(n);
    {
        u8 *dest = buffer;
        walk = buffer;
        fill(dest, n);
    }

When the value is only used after the call, GCC 2.7.2 treats a copy made before it as an equal of the source for
every later read: the second CSE rewrites `walk + K` into `buffer + K`, so a spilled `buffer` is reloaded for the loop
set-up where the game's code reloaded `walk` (`lw $s4` ... `addiu $s2, $s4, 0x3C`). Written after the call the copy is
the loop's own initial value and the register order follows it.

For a copy `U = X;` between two plain identifiers, directly followed by a statement that calls a function and does not
mention `U`, the variants move the copy after that statement, and (when that statement is the last of its block) after
the block's closing brace.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'copy_sink_after_call'
FAMILIES = (FAMILY,)
LIMIT = 6
_COPY = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<to>{IDENT})[ \t]*=[ \t]*(?P<from>{IDENT})[ \t]*;[ \t]*\n')
_CALL = re.compile(rf'[ \t]*(?P<callee>{IDENT})[ \t]*\(')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, base, end = part.clean, part.opening + 1, part.end
    result = []
    for copy in _COPY.finditer(clean, base, end):
        to, origin = copy['to'], copy['from']
        if to == origin or origin in ('NULL', 'return', 'break'):
            continue
        call = _CALL.match(clean, copy.end())
        if not call or call['callee'] in ('if', 'while', 'for', 'switch', 'return', 'sizeof', 'M2C_FIELD'):
            continue
        opening = call.end() - 1
        closing = close(clean, opening)
        if not closing:
            continue
        stop = re.match(r'[ \t]*;[ \t]*\n', clean[closing:])
        if not stop:
            continue
        statement_end = closing + stop.end()
        if re.search(rf'(?<![\w.>]){to}\b', clean[copy.end():statement_end]):
            continue
        places = [(statement_end, copy['indent'])]
        tail = re.match(r'([ \t]*)\}[ \t]*\n', clean[statement_end:])
        if tail:
            places.append((statement_end + tail.end(), tail[1]))
        for place, indent in places:
            result.append((FAMILY, edit(source, [(copy.start(), copy.end(), ''), (place, place, f'{indent}{to} = {origin};\n')])))
    return result[:LIMIT]
