"""A second member of a table element, reached by a subscript of its own so its shift is not shared with the first.

A table of two-halfword records read twice, `T[i].x` then `T[i].y`, compiles to one shift of `i` and a `2(base)` load: cse
gives both addresses the same `i << 2`. A target that shifts twice (`sll v1,a0,2 ... sll a0,a0,2; ori a0,a0,2`) reached
the second member as a flat halfword subscript, `i * 2 + 1`: cse sees `i << 1`, `+ 1`, `<< 1`, nothing the first load
made, and combine folds it to `(i << 2) | 2` afterwards. The subscript must be held in a local: the C front end
distributes a constant inside a subscript (`p[i * 2 + 1]` becomes `(p + i * 2) + 2`). A 48-instruction N64 spawn routine
(SN GCC 2.8.1, `-G0 -mips3 -O2`) was 385 with the member or the `[i * 2 + 1]` form and exact with the local.

Three spellings are rewritten:

member      `T[E].m`, `T` an `extern` array of a struct of equal-width integers, `m` its member k >= 1:
            `j = (E) * N + k; ... ((M *) T)[j]`
subscript   `X[E * N + k]` (literals N >= 2, 1 <= k < N): `j = E * N + k; ... X[j]`
or_offset   m2c's byte offset `(E * S) | K` (K divides S): `((E) * (S / K) + 1) * K`

Every child computes the same address. Proposals only; the compiler and the byte judge decide."""
import re

from .integer_repair_support import view
from .pattern_repairs import close

MEMBER = 'member_flat_subscript'
SUBSCRIPT = 'subscript_sum_local'
OFFSET = 'or_offset_element'
FAMILIES = (MEMBER, SUBSCRIPT, OFFSET)
LIMIT = 8

_WIDTH = r'(?:[su](?:8|16|32)|(?:(?:unsigned|signed)\s+)?(?:char|short|int))'
_STRUCT = re.compile(r'\btypedef\s+struct\s*(?:[A-Za-z_]\w*\s*)?\{([^{}]*)\}\s*([A-Za-z_]\w*)\s*;')
_MEMBERS = re.compile(r'\s*(' + _WIDTH + r')\s+([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*;')
_SUM = re.compile(r'\s*([A-Za-z_]\w*)\s*\*\s*(\d+)\s*\+\s*(\d+)\s*')
_OR = re.compile(r'\(\s*(?:\(\s*([A-Za-z_]\w*)\s*\*\s*(\d+)\s*\)|([A-Za-z_]\w*)\s*\*\s*(\d+))\s*\|\s*(\d+)\s*\)')


def _records(text):
    """{struct typedef name: (member type, [member names])} for structs whose members are all one integer type."""
    found = {}
    for body, name in _STRUCT.findall(text):
        pos, kinds, members = 0, set(), []
        while True:
            hit = _MEMBERS.match(body, pos)
            if not hit:
                break
            kinds.add(' '.join(hit.group(1).split()))
            members += [item.strip() for item in hit.group(2).split(',')]
            pos = hit.end()
        if not body[pos:].strip() and len(kinds) == 1 and len(members) > 1:
            found[name] = (kinds.pop(), members)
    return found


def _statement_start(part, at):
    """Where a statement holding offset `at` can have another put before it, or None (an unbraced arm, a `for` header)."""
    clean = part.clean
    depth = 0
    for pos in range(at - 1, part.opening - 1, -1):
        char = clean[pos]
        if char == ')':
            depth += 1
        elif char == '(':
            depth -= 1
        elif depth <= 0 and char in ';{}':
            start = pos + 1
            while clean[start].isspace():
                start += 1
            return None if re.match(r'(?:else|for|while|do|case|default)\b', clean[start:]) else start
    return None


def _local(part):
    index = 0
    while re.search(r'\bflat_index%d\b' % index, part.clean):
        index += 1
    return 'flat_index%d' % index


def _with_local(source, part, lo, hi, value, use):
    """`source` with [lo, hi) read as `use(local)`, the local set to `value` on the line before."""
    start = _statement_start(part, lo)
    if start is None:
        return None
    local = _local(part)
    line = source.rfind('\n', 0, start) + 1
    indent = source[line:start] if not source[line:start].strip() else '    '
    changed = source[:start] + f'{local} = {value};\n{indent}' + source[start:lo] + use(local) + source[hi:]
    return changed[:part.opening + 1] + f'\n    int {local};' + changed[part.opening + 1:]


def _members(source, part, header):
    context = part.clean + '\n' + header
    records = _records(context)
    if not records:
        return
    arrays = {}
    for kind, array in re.findall(r'\bextern\s+([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*\[\s*\d*\s*\]\s*;', context):
        if kind in records:
            arrays[array] = records[kind]
    for array, (width, members) in arrays.items():
        for hit in re.finditer(r'(?<![\w.>])' + array + r'\s*\[', part.clean[part.opening:part.end]):
            open_at = part.opening + hit.end() - 1
            stop = close(part.clean, open_at, '[', ']')
            if not stop:
                continue
            index = source[open_at + 1:stop - 1].strip()
            member = re.match(r'\s*\.\s*([A-Za-z_]\w*)', part.clean[stop:])
            if not member or member.group(1) not in members[1:] or re.search(r'\+\+|--|\(|=', index):
                continue
            index = index if re.fullmatch(r'[A-Za-z_]\w*', index) else f'({index})'
            value = f'{index} * {len(members)} + {members.index(member.group(1))}'
            yield part.opening + hit.start(), stop + member.end(), value, width, array


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    header = header or ''
    found = []
    for lo, hi, value, width, array in _members(source, part, header):
        found.append((MEMBER, _with_local(source, part, lo, hi, value, lambda j, width=width, array=array: f'(({width} *) {array})[{j}]')))
    body_start = part.opening
    for hit in re.finditer(r'\[', part.clean[body_start:part.end]):
        open_at = body_start + hit.start()
        stop = close(part.clean, open_at, '[', ']')
        if not stop:
            continue
        term = _SUM.fullmatch(part.clean[open_at + 1:stop - 1])
        if term and 0 < int(term.group(3)) < int(term.group(2)):
            found.append((SUBSCRIPT, _with_local(source, part, open_at + 1, stop - 1,
                                                 source[open_at + 1:stop - 1].strip(), lambda j: j)))
    for hit in _OR.finditer(part.clean, body_start, part.end):
        index = hit.group(1) or hit.group(3)
        scale, low = int(hit.group(2) or hit.group(4)), int(hit.group(5))
        if low and not low & (low - 1) and scale % low == 0 and scale // low > 1:
            text = f'((({index}) * {scale // low} + 1) * {low})'
            found.append((OFFSET, source[:hit.start()] + text + source[hit.end():]))
    return [(family, child) for family, child in found if child][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
