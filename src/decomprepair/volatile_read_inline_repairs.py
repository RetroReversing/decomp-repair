"""A volatile read held in a local, read where its call uses it.

A search that needs a value read back from memory it has just stored (`f = 0;` then `x = f;` would otherwise be
folded to a constant) holds the read in a local through a `volatile` cast: `x = *(volatile u16 *)((char *)p + 0x2C);`.
That keeps the load, but it also pins it: the compiler cannot move or merge a volatile access, and the argument move
that goes with it (the hard-register copy GCC 2.x puts in a stall slot) is scheduled around it. On a KMC GCC 2.7.2
N64 function (-O2 -mips3) the local scored 60: only the first argument's `move $a0,$s0` sat in the wrong stall slot.
Writing the same read, plain, in the call's argument list (after the stores to the object's other fields, so cse
cannot fold the earlier store into it) scored 0 (see docs/COMPILER_MATCHING_LEARNINGS.md in decompdecomp).

The local is assigned once, used once, as an argument of a call later in the same block. Between the two the
statements may only store to the same object at other, non-overlapping offsets or assign plain locals; anything else
(a call, a store through another pointer, a store to the bytes read) could change what the read returns and is left
alone. Variants: the read plain at the call, the read volatile at the call (the control), and the plain read as a
statement just before the call. The declaration of the local stays, unused. The exact judge decides.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'volatile_read_inline'
FAMILIES = (FAMILY,)
_SIZE = {'u8': 1, 's8': 1, 'char': 1, 'u16': 2, 's16': 2, 'short': 2, 'u32': 4, 's32': 4, 'int': 4, 'f32': 4,
         'float': 4, 'unsigned': 4}
_READ = re.compile(r'^([ \t]*)(\w+)\s*=\s*\*\(volatile\s+((?:unsigned\s+)?\w+)\s*\*\)\(\(char\s*\*\)\(?(\w+)\)?\s*\+\s*'
                   r'(0[xX][0-9a-fA-F]+|\d+)\)\s*;[ \t]*$')
_STORE = re.compile(r'^\s*\(?\*\(\s*(?:volatile\s+)?((?:unsigned\s+)?\w+)\s*\*\)\(\(char\s*\*\)\(?(\w+)\)?\s*\+\s*'
                    r'(0[xX][0-9a-fA-F]+|\d+)\)\)?\s*=[^=]')
_LOCAL = re.compile(r'^\s*(\w+)\s*=[^=]')
_CALL = re.compile(r'\b[A-Za-z_]\w*\s*\(')


def _stays_clear(text, base, low, size):
    """The statement `text` leaves the bytes [low, low + size) of `base` alone, and calls nothing."""
    if re.search(r'\*[^;=]*=[^=]|->', text) is None and _LOCAL.match(text) and not _CALL.search(text.split('=', 1)[1]):
        return True
    store = _STORE.match(text)
    if not store or store[2] != base or _CALL.search(text.split('=', 1)[1]):
        return False
    start = int(store[3], 0)
    return start + _SIZE.get(store[1].replace('unsigned ', 'u'), 4) <= low or low + size <= start


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    result = []
    pos = source.find('\n', part.opening) + 1
    rows = []
    while 0 < pos < part.end - 1:
        end = source.find('\n', pos)
        end = part.end - 1 if end < 0 or end >= part.end - 1 else end + 1
        rows.append((pos, end, part.clean[pos:end].rstrip('\n')))
        pos = end
    for index, (start, stop, text) in enumerate(rows):
        hit = _READ.match(text)
        if not hit:
            continue
        indent, local, ctype, base, offset = hit.groups()
        low, size = int(offset, 0), _SIZE.get(ctype.replace('unsigned ', 'u'), 0)
        if not size:
            continue
        users = [i for i in range(index + 1, len(rows)) for _ in re.finditer(rf'\b{local}\b', rows[i][2])]
        if len(users) != 1:
            continue
        use = users[0]
        line = rows[use][2]
        if not _CALL.search(line) or re.match(rf'^\s*{local}\s*=', line) or '{' in line or '}' in line:
            continue
        # the rows between are plain statements that cannot reach the bytes read
        if not all(_stays_clear(rows[i][2], base, low, size) for i in range(index + 1, use)):
            continue
        if any('{' in rows[i][2] or '}' in rows[i][2] for i in range(index + 1, use)):
            continue
        spot = re.search(rf'\b{local}\b', line)
        place = rows[use][0] + spot.start()
        plain = f'*({ctype} *)((char *)({base}) + {offset})'
        for read in (plain, plain.replace('*(' + ctype, '*(volatile ' + ctype, 1)):
            result.append((FAMILY, edit(source, [(place, place + len(local), read), (start, stop, '')])))
        before = rows[use][0]
        result.append((FAMILY, edit(source, [(start, stop, ''),
                                             (before, before, f'{indent}{local} = {plain};\n')])))
    return result
