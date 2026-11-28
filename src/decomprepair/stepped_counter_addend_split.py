"""A counter's step and shift done in its own temporary, with the other operand of the sum loaded before them.

m2c writes a field that is advanced, stored back and then shifted into a sum as three statements:

    t = *(s32 *)(p + 0x34) + 1;
    *(s32 *)(p + 0x34) = t;
    h = *(u16 *)(p + 0x3A) + (t >> 2);

On a 25-instruction N64 effect update (SN64 GCC 2.8.1, `-G0 -mips3 -O2 -mgas -meb -mcpu=VR4300 -mhard-float
-mfp64`) the target loads the other operand between the load and the add, keeps the counter in one register through
the shift, and loads the next compared field only after the sum. That came from every step being a set of the same
two locals, with the counter's steps weighted:

    do { PREVIOUS_STATEMENT  t = *(s32 *)(p + 0x34); } while (0);
    h = *(u16 *)(p + 0x3A);
    do { do { do { t++;  *(s32 *)(p + 0x34) = t;  t >>= 2; } while (0); } while (0); } while (0);
    h += t;

270 under the project's compiler and 315 to 445 for typed rewrites under the matching one; this shape was 0. The
one-shot loops are weighting scaffolding (flow.c counts a reference once more per loop; hypothesis that this is what
moves the registers here), so children without them are offered too. One function: a candidate for the exact judge.

The other operand moves above the counter's store, so it is only taken when it cannot be that place: a local or
literal, or a load of a different constant offset (or another member) of the same base. The temporary is a 32-bit
local that is not read again before it is set, the sum's local an integer, and nothing volatile is touched.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'stepped_counter_addend_split'
FAMILIES = (FAMILY,)
LIMIT = 3  # sites

_WIDE = r'(?:s32|u32|int|unsigned\s+int|long)'
_INTEGER = r'(?:s32|u32|int|unsigned\s+int|long|s16|u16|short|s8|u8|char)'
_STATEMENT = re.compile(r'([^;{}]+);')
_KEYWORD = re.compile(r'\b(?:if|else|for|while|do|switch|case|default|goto|return|break|continue)\b|(?<![?\w])\w+\s*:(?!:)')
_SIZES = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'long': 4}


def _bare(text):
    """`text` without the parentheses that wrap the whole of it."""
    text = text.strip()
    while text.startswith('(') and text.endswith(')'):
        depth = 0
        for at, char in enumerate(text):
            depth += (char == '(') - (char == ')')
            if not depth and at < len(text) - 1:
                return text
        text = text[1:-1].strip()
    return text


def _squeeze(text):
    return re.sub(r'\s+', '', _bare(text))


def _load(text):
    """(base, offset, size) of `*(T *)(base + K)` in its spellings, or None."""
    found = re.fullmatch(rf'\*\(*({_INTEGER}|f32|float)\*\)\(*(?:\((?:char|u8|s8)\*\))?\(?([A-Za-z_]\w*)\)?\)?'
                         rf'\+(0x[0-9A-Fa-f]+|\d+)\)+', _squeeze(text))
    if not found:
        return None
    kind, base, offset = found.groups()
    return base, int(offset, 0), _SIZES.get(kind), kind


def _member(text):
    found = re.fullmatch(r'([A-Za-z_]\w*)(->|\.)([A-Za-z_]\w*)', _squeeze(text))
    return found.groups() if found else None


def _apart(addend, place, source, body):
    """Whether `addend` is an integer value that storing to `place` cannot change."""
    plain = _squeeze(addend)
    if re.fullmatch(r'\d+|0x[0-9A-Fa-f]+', plain):
        return True
    if re.fullmatch(r'[A-Za-z_]\w*', plain):
        return bool(re.search(rf'\b{_INTEGER}\s+{plain}\s*[;,)=]', source)) and not re.search(rf'&\s*{plain}\b', body)
    first, second = _load(addend), _load(place)
    if first and second:
        return (first[3] not in ('f32', 'float') and first[0] == second[0] and bool(first[2] and second[2])
                and (first[1] + first[2] <= second[1] or second[1] + second[2] <= first[1]))
    first, second = _member(addend), _member(place)
    if first and second and first[:2] == second[:2] and first[2] != second[2]:
        return (bool(re.search(rf'\b{_INTEGER}\s+{first[2]}\s*;', source))
                and not re.search(r'\bunion\b', source))
    return False


def _sum(text):
    """The two sides of `A + (B >> K)` at the top level, as (addend, shifted name, K), in either order."""
    depth = 0
    for at, char in enumerate(text):
        depth += (char in '([') - (char in ')]')
        if char == '+' and not depth and text[at + 1:at + 2] not in '+=' and text[at - 1:at] != '+':
            for addend, shifted in ((text[:at], text[at + 1:]), (text[at + 1:], text[:at])):
                found = re.fullmatch(r'([A-Za-z_]\w*)>>(\d+|0x[0-9A-Fa-f]+)', _squeeze(shifted))
                if found:
                    yield addend.strip(), found.group(1), found.group(2)


def _dead_after(text, name):
    found = re.search(rf'\b{name}\b', text)
    return not found or bool(re.match(rf'{name}\s*=(?!=)', text[found.start():])) and \
        not re.search(r'[{}]|\bgoto\b', text[:found.start()])


def _sites(source, part):
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    body = clean[lo:hi]
    rows = list(_STATEMENT.finditer(clean, lo, hi))
    for index in range(len(rows) - 2):
        step, store, total = rows[index], rows[index + 1], rows[index + 2]
        if any(clean[left.end():right.start()].strip() for left, right in ((step, store), (store, total))):
            continue
        read = re.fullmatch(r'\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*\+\s*1\s*', step.group(1), re.S)
        if not read:
            continue
        counter, place = read.group(1), read.group(2)
        kept = re.fullmatch(rf'\s*(.+?)\s*=\s*{counter}\s*', store.group(1), re.S)
        if not kept or _squeeze(kept.group(1)) != _squeeze(place) or re.search(rf'\b{counter}\b', place):
            continue
        written = re.fullmatch(r'\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*', total.group(1), re.S)
        if not written or written.group(1) == counter:
            continue
        result = written.group(1)
        if (not re.search(rf'(?m)^[ \t]*{_WIDE}\s+{counter}\s*;', body)
                or not re.search(rf'(?m)^[ \t]*{_INTEGER}\s+{result}\s*;', body)
                or re.search(rf'&\s*(?:{counter}|{result})\b', body)
                or re.search(rf'\b{result}\b', place) or not _dead_after(clean[total.end():hi], counter)):
            continue
        for addend, shifted, amount in _sum(written.group(2)):
            if (shifted == counter and not re.search(rf'\b(?:{counter}|{result})\b|\+\+|--', addend)
                    and _apart(addend, place, source, body)):
                yield rows[index - 1] if index else None, step, store, total, counter, result, addend, amount
                break


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\bvolatile\b', part.clean[part.opening:part.end]):
        return []
    out = []
    for before, step, store, total, counter, result, addend, amount in list(_sites(source, part))[:LIMIT]:
        place = source[store.start(1):store.end(1)].rsplit('=', 1)[0].strip()
        start = step.start(1) + len(step.group(1)) - len(step.group(1).lstrip())
        indent = source[source.rfind('\n', 0, start) + 1:start]
        indent = indent if not indent.strip() else '  '
        loaded = _bare(addend)
        previous = None
        if before is not None and not part.clean[before.end():step.start()].strip() \
                and not _KEYWORD.search(before.group(1)) and re.search(r'=|\+\+|--|\(', before.group(1)) \
                and not re.match(rf'\s*(?:const\s+)?(?:{_INTEGER}|f32|void|struct\s+\w+)\b[\s*]+\w', before.group(1)):
            previous = before
        read = f'{counter} = {place};'
        heads = [(start, read)]
        if previous is not None:
            at = previous.start(1) + len(previous.group(1)) - len(previous.group(1).lstrip())
            kept = source[at:previous.end()]
            heads = [(at, f'do {{ {kept} {read} }} while (0);'), (at, f'{kept}\n{indent}{read}'),
                     (start, f'do {{ {read} }} while (0);')]
        steps = f'{counter}++; {place} = {counter}; {counter} >>= {amount};'
        for depth in (3, 1, 0):
            inner = steps
            for _ in range(depth):
                inner = f'do {{ {inner} }} while (0);'
            for at, head in heads:
                lines = [head, f'{result} = {loaded};', inner, f'{result} += {counter};']
                out.append((FAMILY, edit(source, [(at, total.end(), f'\n{indent}'.join(lines))])))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
