"""Some of a volatile pointer's reads written through a plain cast, so the compiler may treat them as ordinary loads (GCC 2.7.2, KMC, N64).

A cursor an agent declared `volatile` to keep a loop's loads in program order (`const volatile u8 *q;`) makes every read of it
an access the compiler may not move, merge or fold. The game's loads were not all like that: a 16-bit value read as two
bytes and added (`(q[0] << 8) + q[1]`) is `addu` of two registers in the target, where a pair of volatile byte loads stays two
`zero_extend`s of QImode registers and the add comes out with its operands the other way round (the first operand of the
add is the shifted high byte in the target and the low byte in the volatile pair, whichever way the C writes it). Reading
only the low byte through `((u8 *) q)[i * 6 + 1]` left the high byte volatile and the add as the target has it:
measured on a 559-instruction N64 display-list builder (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`), 20 -> 0 with the
low bytes (the odd offsets) of the two loops' byte pairs un-pinned, in the same judge: the second loop's alone was 15
and the first loop's alone 5, the two together 0.

`variants` takes each brace block (a loop body or an arm) of a function that reads a `volatile` pointer and writes the
reads of it in that block as plain loads: every read (`volatile_read_subset_unpin`), the reads at an odd constant offset
(`q[i * 6 + 1]`: the low bytes of byte pairs), the reads at an even one, and the first read alone, one child per
block; the children of different blocks edit different text, so a chain composes them. A read stays volatile when it is
written through or stepped.
"""
import re

from .csource import find
from .pattern_repairs import close

FAMILY = 'volatile_read_subset_unpin'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_DECL = re.compile(rf'(?m)^[ \t]*(?P<quals>(?:const\s+|volatile\s+)+)?(?P<type>(?:[su](?:8|16|32)|unsigned\s+\w+|char|short|int))\s*'
                   rf'(?P<quals2>(?:const\s+|volatile\s+)*)\*\s*(?P<name>{_ID})\s*;')
MAX_CHILDREN = 8


def _pointers(text):
    """name -> plain cast type for each local pointer declared `volatile` (the cast keeps `const`)."""
    out = {}
    for hit in _DECL.finditer(text):
        quals = ' '.join(filter(None, [hit['quals'] or '', hit['quals2'] or ''])).split()
        if 'volatile' not in quals:
            continue
        const = 'const ' if 'const' in quals else ''
        out[hit['name']] = f'{const}{" ".join(hit["type"].split())} *'
    return out


def _statements(text):
    """The `{ ... }` bodies (loops, arms) as (start, end) of their inner text, innermost last."""
    out, stack = [], []
    for pos, char in enumerate(text):
        if char == '{':
            stack.append(pos)
        elif char == '}' and stack:
            out.append((stack.pop() + 1, pos))
    return sorted(out)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    text = source[span[0]:span[1]]
    pointers = _pointers(text)
    if not pointers:
        return []
    children = []
    blocks = _statements(text)
    for pointer, cast in pointers.items():
        reads = []
        for hit in re.finditer(rf'(?<![\w.>*&]){re.escape(pointer)}\s*\[', text):
            shut = close(text, hit.end() - 1, '[', ']')
            if not shut:
                continue
            if re.match(r'\s*(?:=(?!=)|[-+*/|&^]=|<<=|>>=|\+\+|--)', text[shut:shut + 12]):
                continue
            reads.append((hit.start(), _offset(text[hit.end():shut - 1])))
        # group the reads by the innermost braces that hold them: a loop body or an arm
        groups = {}
        for at, offset in reads:
            inner = max((b for b in blocks if b[0] <= at < b[1]), key=lambda b: b[0], default=None)
            if inner is not None:
                groups.setdefault(inner, []).append((at, offset))
        for group in groups.values():
            picks = [[at for at, _ in group],
                     [at for at, offset in group if offset % 2 == 1],
                     [at for at, offset in group if offset % 2 == 0],
                     [group[0][0]]]
            seen = []
            for pick in picks:
                if not pick or pick in seen:
                    continue
                seen.append(pick)
                child = text
                for at in sorted(pick, reverse=True):
                    child = child[:at] + f'(({cast}) {pointer})' + child[at + len(pointer):]
                children.append((FAMILY, source[:span[0]] + child + source[span[1]:]))
    return list(dict.fromkeys(children))[:MAX_CHILDREN * 4]


def _offset(index):
    """The constant part of an index (`i * 6 + 3` is 3, `i * 2` is 0, `5` is 5): parity says high byte or low byte."""
    tail = re.search(r'\+\s*(0[xX][0-9a-fA-F]+|\d+)\s*$', index)
    if tail:
        return int(tail[1], 0)
    return int(index, 0) if re.fullmatch(r'\s*(?:0[xX][0-9a-fA-F]+|\d+)\s*', index) else 0


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
