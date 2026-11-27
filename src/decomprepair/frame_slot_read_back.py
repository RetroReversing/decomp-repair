"""A temporary stored into a local array's element, read back later as that element instead of the temporary.

    t = acc >> 12;  sp0[0] = t;  ...  x = G * t;     ->     ...  x = G * sp0[0];

m2c names a value it sees stored to a frame slot and used again, and writes the later use as the temporary. When the
original read the element, gcc's cse still finds the stored value in the register (no load appears), but the operand it
substitutes is the register as a replacement for a memory read, and a commutative operation keeps the order the source
gave it: `mult $v0,$t0` (the global first) against `mult $t0,$v0` from the temporary. Swapping the operands in C left
the row (an SN GCC 2.7.2 `-O1` projection routine, 5 -> 0 by reading `sp0[0]`). The cse reading is a hypothesis; the
judge decides.

frame_slot_read_back
    `A[N] = T;` with A a local array, N an integer literal and T an identifier assigned once, before that line, and
    read on a later line. Children: each later line that reads T with T written `A[N]` there, and all of them at once
    when there are several. At most 8.
"""
import re

from .csource import _blank, find

FAMILY = 'frame_slot_read_back'
FAMILIES = (FAMILY,)
ID = r'[A-Za-z_]\w*'
NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
LIMIT = 8


def _body(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return None
    depth = 0
    for i in range(opening, span[1]):
        depth += (clean[i] == '{') - (clean[i] == '}')
        if depth == 0:
            return opening, i + 1
    return None


def _writes(line, name):
    return bool(re.search(rf'(?<![\w.>])\b{name}\s*(?:[-+*/&|^%]|<<|>>)?=(?!=)', line)
                or re.search(rf'(?:\+\+|--)\s*{name}\b|\b{name}\s*(?:\+\+|--)', line)
                or re.search(rf'(?:^|[(,=;{{!~?:]|\breturn)\s*&\s*{name}\b', line))


def variants(source, name):
    part = _body(source, name)
    if not part:
        return []
    opening, end = part
    head, body, tail = source[:opening + 1], source[opening + 1:end - 1], source[end - 1:]
    lines = body.split('\n')
    arrays = {m[1] for line in lines for m in [re.fullmatch(rf'\s*(?!return\b|goto\b|case\b)(?:{ID}\s+)+({ID})\s*\[\s*{NUM}?\s*\]\s*;\s*', line)] if m}
    if not arrays:
        return []
    out = []
    for at, line in enumerate(lines):
        m = re.fullmatch(rf'\s*(?P<a>{ID})\s*\[\s*(?P<n>{NUM})\s*\]\s*=\s*(?P<t>{ID})\s*;\s*', line)
        if not m or m['a'] not in arrays or m['t'] in arrays:
            continue
        t = m['t']
        writes = [i for i, other in enumerate(lines) if _writes(other, t)]
        if len(writes) != 1 or writes[0] >= at:
            continue
        element = f"{m['a']}[{m['n']}]"
        later = [i for i in range(at + 1, len(lines)) if re.search(rf'\b{t}\b', lines[i])]
        store = re.compile(rf'\b{m["a"]}\s*\[\s*{m["n"]}\s*\]\s*(?:[-+*/&|^%]|<<|>>)?=(?!=)|&\s*{m["a"]}\b')
        if not later or any(store.search(lines[i]) for i in range(at + 1, later[-1] + 1)):
            continue
        choices = [[i] for i in later] + ([later] if len(later) > 1 else [])
        for chosen in choices:
            new = list(lines)
            for i in chosen:
                new[i] = re.sub(rf'\b{t}\b', element, new[i])
            out.append((FAMILY, head + '\n'.join(new) + tail))
            if len(out) >= LIMIT:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
