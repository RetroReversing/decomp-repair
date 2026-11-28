"""A call's trailing argument that only repeats the index inside an earlier one, dropped with the prototype.

m2c names whatever an argument register still holds at a call. A call whose first argument is `table + i * 50`, with
`i` loaded into the next free argument register to compute it, comes back as `f(table + i * 50, format, name, i)`,
with a prototype of four parameters to fit. The arity families take trailing constants, parameters and globals out;
this one takes the value that was only on its way into the address.

repeated_index_argument
    Every call whose last argument (a read of a variable or member, casts aside) appears again inside an earlier
    argument has it dropped, and the callee's prototype in this source is written `()`. All calls together, since the
    tails of two paths the compiler merges must agree.

Seen on an SN GCC 2.8.1 (`-G0 -mips3 -O2`) N64 label update that formats one of two strings (one function, a
controlled result: part of its match). The judge decides whether the callee did take the value.
"""
import re

from .csource import _blank, find
from .integer_repair_support import edit
from .m2cfix import _split_top_level
from .pattern_repairs import close

FAMILY = 'repeated_index_argument'
FAMILIES = (FAMILY,)

_CAST = re.compile(r'^\(\s*(?:s8|u8|s16|u16|s32|u32|int)\s*\)\s*')


def _arguments(clean, opening, end):
    """(start, end) of each top-level argument of the call whose parentheses are [opening, end)."""
    found, start = [], opening + 1
    for part in _split_top_level(clean[opening + 1:end - 1]):
        found.append((start, start + len(part)))
        start += len(part) + 1
    return found


def _value(text):
    """The argument without casts, outer parentheses and spaces; None when it is not one read."""
    text = text.strip()
    while True:
        before = text
        while text.startswith('(') and close(text, 0) == len(text):
            text = text[1:-1].strip()
        text = _CAST.sub('', text)
        if text == before:
            break
    plain = re.sub(r'\(\s*\(\s*[A-Za-z_]\w*\s*\*+\s*\)\s*([A-Za-z_]\w*)\s*\)', r'\1', text)
    if not re.fullmatch(r'[A-Za-z_]\w*(?:\s*(?:->|\.)\s*[A-Za-z_]\w*)*', plain):
        return None
    return re.sub(r'\s+', '', text)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    callees = {}
    for hit in re.finditer(r'(?<![\w.>])([A-Za-z_]\w*)\s*\(', clean[opening:span[1]]):
        if hit[1] in ('if', 'while', 'for', 'switch', 'return', 'sizeof', 'M2C_FIELD'):
            continue
        at = opening + hit.end() - 1
        end = close(clean, at)
        if not end:
            continue
        arguments = _arguments(clean, at, end)
        if len(arguments) < 2:
            continue
        last = _value(source[slice(*arguments[-1])])
        if not last:
            continue
        earlier = ''.join(re.sub(r'\s+', '', source[slice(*a)]) for a in arguments[:-1])
        if re.search(r'(?<![\w.>])' + re.escape(last) + r'(?![\w])', earlier):
            callees.setdefault(hit[1], []).append((arguments[-2][1], arguments[-1][1], ''))
    result = []
    for callee, edits in callees.items():
        prototype = re.search(rf'(?m)^[ \t]*(?:extern\s+)?[A-Za-z_][\w ]*?[\s*]+{re.escape(callee)}\s*\(', clean[:span[0]])
        if not prototype:
            continue  # a shared declaration this source cannot relax
        at = prototype.end() - 1
        end = close(clean, at)
        if not end or not re.match(r'\s*;', clean[end:]):
            continue
        result.append((FAMILY, edit(source, edits + [(at + 1, end - 1, '')])))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
