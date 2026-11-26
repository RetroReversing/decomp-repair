"""m2c's byte offsets off one global, written as the record array the game declared there.

A table initialiser reads back from m2c as one big symbol and offsets: `temp = (char *)&D_x + 0x2108;`, then
`M2C_FIELD(temp, s16 *, 0x2A) = 3;` and in a loop `*((char *)&D_x + 0x2108 + ((i & 0xFF) * 0x28)) = 0;`. The game
declared an array of records at that address, and GCC treats the two differently: member stores of a declared array
under KMC `-O1` go through one register that holds the address, while casts and a pointer local do not. A 53-instruction
N64 initialiser sat at 525 through 40 attempts and was exact from its draft with this record array under `-O1`
(7075 under either level before it).

The stride comes from the indexed access; without one the offsets are one record. Two children: the array declared at
its own address (`extern Row D_x_plus_offset[];`, for address-named symbols), and the array as a member of a padded
record at the original symbol. Nothing is rewritten unless every use of the symbol and of its alias is understood.
"""
import re

from .m2c_field_record_view import POINTER, SIZES, _definition

FAMILY = 'global_offset_records'
FAMILIES = (FAMILY,)
_NUMBER = r'(?:0x[0-9A-Fa-f]+|\d+)'
_BYTES = r'(?:\(\s*(?:char|s8|u8)\s*\*\s*\)\s*)'
_ADDRESS_NAME = re.compile(r'D_([0-9A-F]{8})')
TAG = 'OffsetRow'


def _closing(text, start):
    """The index of the parenthesis that closes the one at `start`, or None."""
    depth = 0
    for at in range(start, len(text)):
        depth += {'(': 1, ')': -1}.get(text[at], 0)
        if depth == 0:
            return at
    return None


def _indexed(body, symbol):
    """The accesses `*((char *)&symbol + base + (index * stride))`: [(start, end, base, index, stride)]."""
    head = re.compile(r'\*\(\s*' + _BYTES + r'&\s*' + symbol + r'\s*\+\s*(' + _NUMBER + r')\s*\+\s*\(')
    found = []
    for match in head.finditer(body):
        outer = _closing(body, match.start() + 1)
        inner = _closing(body, match.end() - 1)
        if outer is None or inner is None or body[inner + 1:outer].strip():
            return None
        product = re.fullmatch(r'(.+?)\s*\*\s*(' + _NUMBER + r')', body[match.end():inner].strip(), re.S)
        if not product:
            return None
        index = product[1].strip()
        if index.startswith('(') and _closing(index, 0) == len(index) - 1:
            index = index[1:-1].strip()
        found.append((match.start(), outer + 1, int(match[1], 0), index, int(product[2], 0)))
    return found


def _plan(source, name, symbol):
    """(base, stride, members, edits, aliases) for one symbol, or None when a use is not understood."""
    start = _definition(source, name)
    body = source[start:]
    aliases = {m[1]: (int(m[2], 0), m.span()) for m in re.finditer(
        r'^[ \t]*([A-Za-z_]\w*)\s*=\s*' + _BYTES + r'&\s*' + symbol + r'\s*\+\s*(' + _NUMBER + r')\s*;[ \t]*\n',
        body, re.M)}
    roots = {alias: offset for alias, (offset, _) in aliases.items()}
    field = re.compile(r'\bM2C_FIELD\(\s*(&\s*' + symbol + r'\b|(?:' + '|'.join(map(re.escape, roots or ['(?!)']))
                       + r')\b)\s*,\s*([A-Za-z_]\w*)\s*(\*+)\s*,\s*(-?' + _NUMBER + r')\s*\)')
    scalar = []
    for m in field.finditer(body):
        member, size = ('void *', POINTER) if len(m[3]) > 1 else (m[2], SIZES.get(m[2]))
        if size is None:
            return None
        offset = int(m[4], 0) + roots.get(m[1], 0)
        scalar.append((m.start(), m.end(), offset, member, size))
    indexed = _indexed(body, symbol)
    if indexed is None or len(scalar) < 3 or len({(base, stride) for _, _, base, _, stride in indexed}) > 1:
        return None
    if indexed:
        base, stride = indexed[0][2], indexed[0][4]
    else:
        base, stride = min(offset for _, _, offset, _, _ in scalar), None
    members = {}
    for _, _, offset, member, size in scalar:
        if offset < base:
            return None
        inside = (offset - base) % stride if stride else offset - base
        if inside % size or (stride and inside + size > stride) or members.setdefault(inside, (member, size)) != (member, size):
            return None
    ordered = sorted(members.items())
    if any(at + size > later for (at, (_, size)), (later, _) in zip(ordered, ordered[1:])):
        return None
    if indexed and 0 not in members:
        return None
    edits = [(a, b, f'{{rows}}[{(offset - base) // stride if stride else 0}].m{(offset - base) % stride if stride else offset - base:X}')
             for a, b, offset, _, _ in scalar]
    edits += [(a, b, f'{{rows}}[{index}].m0') for a, b, _, index, _ in indexed]
    edits += [(a, b, '') for _, (a, b) in aliases.values()]
    return base, stride, dict(ordered), edits, list(aliases)


def _record(members, stride):
    lines, at = [], 0
    for offset, (member, size) in members.items():
        if offset > at:
            lines.append(f'    char pad{at:X}[0x{offset - at:X}];')
        space = '' if member.endswith('*') else ' '
        lines.append(f'    {member}{space}m{offset:X};')
        at = offset + size
    if stride and stride > at:
        lines.append(f'    char pad{at:X}[0x{stride - at:X}];')
    return 'typedef struct {\n' + '\n'.join(lines) + f'\n}} {TAG};\n'


def _apply(source, name, symbol, plan, rows, declaration):
    base, stride, members, edits, aliases = plan
    start = _definition(source, name)
    head, body = source[:start], source[start:]
    edits = sorted(edits)
    if any(first[1] > second[0] for first, second in zip(edits, edits[1:])):
        return None
    for a, b, text in reversed(edits):
        body = body[:a] + text + body[b:]
    for alias in aliases:
        body = re.sub(r'^[ \t]*(?:void|char|s8|u8|s16|u16|s32|M2C_UNK\d*)\s*\*\s*' + re.escape(alias) + r'\s*;[ \t]*\n', '', body, flags=re.M)
        if re.search(r'\b' + re.escape(alias) + r'\b', body):
            return None
    if re.search(r'\b' + symbol + r'\b', body):
        return None
    head, found = re.subn(r'^[ \t]*extern\s+[\w \t]+?[\s*]' + symbol + r'\s*(?:\[[^\]\n]*\])?\s*;[ \t]*\n', '', head, flags=re.M)
    if re.search(r'\b' + symbol + r'\b', head) or (found == 0 and declaration is None):
        return None
    return head, body.replace('{rows}', rows)


def variants(source, name, header=''):
    start = _definition(source, name)
    if start is None or 'M2C_FIELD(' not in source or re.search(r'\b' + TAG + r'\b', source + header):
        return []
    body = source[start:]
    symbols = dict.fromkeys(re.findall(_BYTES + r'&\s*([A-Za-z_]\w*)\s*\+', body))
    out = []
    for symbol in list(symbols)[:4]:
        plan = _plan(source, name, symbol)
        if plan is None:
            continue
        base, stride, members = plan[:3]
        record = _record(members, stride)
        address = _ADDRESS_NAME.fullmatch(symbol)
        if address and base:
            rows = f'D_{int(address[1], 16) + base:08X}'
            if not re.search(r'\b' + rows + r'\b', source + header):
                applied = _apply(source, name, symbol, plan, rows, rows)
                if applied:
                    out.append((FAMILY, applied[0] + record + f'extern {TAG} {rows}[];\n\n' + applied[1]))
        # the same array as a member of a record at the symbol the source already names
        if not re.search(r'\b' + symbol + r'\b', header):
            count = 1 + max((int(text[len('{rows}['):text.index(']')]) for _, _, text in plan[3]
                             if re.match(r'\{rows\}\[\d+\]', text)), default=0)
            if plan[1]:
                count = 0  # the loop reaches rows no constant names: a trailing array of GNU C's zero length
            pad = f'    char pad[0x{base:X}];\n' if base else ''
            whole = f'typedef struct {{\n{pad}    {TAG} rows[{count}];\n}} {TAG}Table;\n'
            applied = _apply(source, name, symbol, plan, f'{symbol}.rows', symbol)
            if applied:
                out.append((FAMILY, applied[0] + record + whole + f'extern {TAG}Table {symbol};\n\n' + applied[1]))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
