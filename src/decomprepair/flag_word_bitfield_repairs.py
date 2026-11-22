"""A flag word that is read, masked, or-ed and stored back, with a byte stored over it, written as bit-fields.

m2c writes the update of a packed word as `flags = p->flags; p->flags = (flags & ~0xfc) | 0x1c;` and a store into
its top byte as `*(u8 *)&p->flags = v;`. A search that cannot spell the original keeps the arithmetic and a
`volatile` pointer to hold the access order, and stalls a few points short. An N64 object-placement function (KMC GCC
2.7.2, 34 instructions) sat at 15 for hundreds of trials: three register differences on the first coordinate. The
word was a bit-field struct (`u32 color:8; u32 mid:16; u32 kind:6; u32 low:2;`), written `p->kind = 7;` and
`p->color = v;`: gcc emits the same `lw; and; ori; sw; sb` for those, and the pointer then needs no `volatile`.
Written that way with the store of the constant scale moved ahead of the first coordinate store it was exact; the
bit-field alone left 775 (volatile pointer kept), 265 (volatile dropped) and the reorder reached 0. A controlled
reproduction of one function, not a corpus result.

Hypothesis, not confirmed in the compiler source: the volatile pointer made every access a barrier, so the register
allocator saw the three coordinate loads as one long live range; plain field accesses let the scheduler interleave
them as the target does.

Needs a big-endian target (bit-fields fill from the most significant bit, and a byte store at the word's address is
its top byte): the family only reads the bit positions, so a little-endian game gets variants that fail to match and
cost one compile each. Variants, each a candidate for the exact judge: the bit-field spelling alone; with the
pointer's `volatile` dropped; either one with the first literal store through the pointer moved ahead of its first
other store; and the volatile drop combined with that move, the chain that matched.
"""
import re

from .integer_repair_support import view

FAMILY = 'flag_word_bitfield'
FAMILIES = (FAMILY,)

_NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
_WORD_TYPES = r'(?:u32|s32|unsigned\s+int|unsigned|int|u_int)'


def _num(text):
    return int(text, 0)


def _edit(source, edits):
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def _bits(mask):
    low = (mask & -mask).bit_length() - 1
    run = mask >> low
    return (low, run.bit_length()) if mask and run & (run + 1) == 0 else None


def _update(clean):
    """The masked update `p->f = (src & ~M) | C;` as (match, pointer, field, source operand, mask, value)."""
    for hit in re.finditer(rf'(?P<ptr>\w+)->(?P<f>\w+)\s*=\s*\(\s*(?P<src>\w+(?:->\w+)?)\s*&\s*'
                           rf'(?P<inv>~)?\s*(?P<mask>{_NUM})u?\s*\)\s*\|\s*(?P<val>{_NUM})u?\s*;', clean):
        mask = _num(hit['mask']) & 0xFFFFFFFF
        mask = mask if hit['inv'] else ~mask & 0xFFFFFFFF
        value = _num(hit['val'])
        place = _bits(mask)
        if not place or value & ~mask or mask & 0xFF000000 == 0xFF000000 or hit['src'] not in (hit['ptr'] + '->' + hit['f'], *re.findall(r'\w+', hit['src'])[:1]):
            continue
        return hit, hit['ptr'], hit['f'], hit['src'], place, value
    return None


def _hoist(source, name, ptr):
    """The first literal store through `ptr`, moved ahead of its first other store (same indentation), or None."""
    part = view(source, name)
    rows = []
    pos = part.opening
    for line in source[part.opening:part.end].split('\n'):
        rows.append((pos, pos + len(line) + 1, line))
        pos += len(line) + 1
    store = re.compile(rf'^([ \t]*){re.escape(ptr)}->(\w+)\s*=\s*(.+);$')
    first = None
    for index, (start, end, text) in enumerate(rows):
        hit = store.match(text)
        if not hit or text.count('=') != 1:
            continue
        literal = re.fullmatch(rf'{_NUM}', hit[3].strip()) is not None
        if first is None:
            if literal:
                return None   # already first
            first = (index, hit[1])
        elif literal and hit[1] == first[1]:
            moved = source[start:end]
            return _edit(source, [(start, end, ''), (rows[first[0]][0], rows[first[0]][0], moved)])
    return None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    found = _update(part.clean[part.opening:part.end])
    if not found:
        return []
    hit, ptr, field, src, (low, width), value = found
    base = part.opening
    # the struct member `u32 field;` is the one place that gives the word its layout
    members = list(re.finditer(rf'(?m)^([ \t]*){_WORD_TYPES}[ \t]+{re.escape(field)}[ \t]*;[ \t]*$', part.clean[:part.opening]))
    if len(members) != 1:
        return []
    member = members[0]
    byte = re.search(rf'\*\s*\(\s*(?:volatile\s+)?u8\s*\*\s*\)\s*&\s*{re.escape(ptr)}->{re.escape(field)}\s*=\s*([^;]+);',
                     part.clean[part.opening:part.end])
    top = 8 if byte else 0
    middle = 32 - top - width - low
    if middle < 0:
        return []
    parts = [(f'{field}_byte', top), (f'{field}_mid', middle), (f'{field}_set', width), (f'{field}_low', low)]
    members_text = member[1] + ' '.join(f'u32 {n}:{w};' for n, w in parts if w)
    edits = [(member.start(), member.end(), members_text),
             (base + hit.start(), base + hit.end(), f'{ptr}->{field}_set = {value >> low};')]
    if byte:
        value_text = source[base + byte.start(1):base + byte.end(1)].strip()
        edits.append((base + byte.start(), base + byte.end(), f'{ptr}->{field}_byte = {value_text};'))
    # the read of the word into the local (`flags = p->flags;`) and its declaration are dead once nothing masks it
    if src != f'{ptr}->{field}':
        body = part.clean[part.opening:part.end]
        read = re.search(rf'(?m)^[ \t]*{re.escape(src)}\s*=\s*{re.escape(ptr)}->{re.escape(field)}\s*;[ \t]*\n', body)
        declared = re.search(rf'(?m)^[ \t]*{_WORD_TYPES}[ \t]+{re.escape(src)}[ \t]*;[ \t]*\n', body)
        uses = re.findall(rf'(?<![>\w]){re.escape(src)}\b', body)
        if not read or len(uses) != 2 + bool(declared):
            return []   # the word is read for another purpose: the arithmetic stays
        edits.append((base + read.start(), base + read.end(), ''))
        if declared:
            edits.append((base + declared.start(), base + declared.end(), ''))
    plain = _edit(source, edits)
    out = [plain]
    dropped = re.sub(rf'volatile\s+((?:struct\s+)?\w+\s*\*\s*{re.escape(ptr)}\s*;)', r'\1', plain, count=1)
    if dropped != plain:
        out.append(dropped)
    for variant in list(out):
        moved = _hoist(variant, name, ptr)
        if moved:
            out.append(moved)
    return [(FAMILY, text) for text in dict.fromkeys(out)]

