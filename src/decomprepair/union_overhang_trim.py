"""A frame union's overhanging view trimmed, and m2c's spilled `spXX` locals declared in slot order.

m2c (and agents after it) give a stack buffer that the function reads at several offsets a union of views:
`union { f32 data[6]; struct { f32 pad[4]; f32 lower[3]; } bounds; } w;`. When a view reaches past the largest
plain array (16 + 12 = 28 bytes against 24), the union grows, and GCC 2.7.2 rounds every stack aggregate up to
8 bytes (`assign_stack_local`), so the whole frame is 8 bytes larger than the target's and every later local and
spill slot moves. The game wrote the plain array and addressed past it (`&w.data[4]`, its last element landing in
the next local, as the target's offsets show); the trim writes the view's members as elements of the plain array
of the same element type (`w.bounds.lower[i]` -> `w.data[4 + i]`, `w.bounds.lower` -> `&w.data[4]`) and drops the
view.

Pseudos that reload spills get their slots in pseudo order (reload1.c `alter_reg`, in increasing register
number), and a local's pseudo is made when its declaration is expanded, so the spill slots follow the declaration
order of the locals that spill. m2c names such a local after its slot in the target (`spE4`, `sp12E`): a function
whose `spXX` scalars are declared out of hex order puts them in other slots. `spill_name_order` re-declares them
(only top-level scalar declarations, one per line) in increasing slot order, in the places the old ones held.

The two pay off only together when the frame is the cause: on a KMC GCC 2.7.2 N64 collision sweep
(`-G0 -mips3 -mgp32 -mfp32 -O2`, 1337 instructions) the trim alone moved every spill slot 8 bytes down
(10972 -> 11651) and the order alone left them 8 bytes high (11427), while both fixed the frame and all but two
stack rows (10972 -> 10589). So `variants` offers the combination first, then each part alone (hypothesis for
the slot rule: read from reload1.c and the dumps of that one function)."""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILIES = ('union_overhang_spill_order', 'union_overhang_trim', 'spill_name_order')
LIMIT = 8
_IDENT = r'[A-Za-z_]\w*'
_SCALAR = re.compile(r'(?m)^[ \t]*(?:register[ \t]+)?(?:(?:unsigned|signed|const|struct|union)[ \t]+)*'
                     r'[A-Za-z_]\w*(?:[ \t]*\*)*[ \t]*\b(sp([0-9A-Fa-f]+))[ \t]*;[ \t]*\n')
_ARRAY = re.compile(r'^\s*((?:unsigned\s+|signed\s+)?' + _IDENT + r')\s+(' + _IDENT + r')\s*\[\s*(\d+)\s*\]\s*$')


def spill_order(source, name):
    """The function's top-level `spXX` scalar declarations re-declared in slot order, or None."""
    part = view(source, name)
    if not part:
        return None
    hits = []
    for hit in _SCALAR.finditer(part.clean, part.opening + 1, part.end):
        if _depth(part, hit.start()) == 1:
            hits.append(hit)
    ordered = sorted(hits, key=lambda hit: int(hit[2], 16))
    if len(hits) < 2 or ordered == hits:
        return None
    return edit(source, [(slot.start(), slot.end(), source[hit.start():hit.end()]) for slot, hit in zip(hits, ordered)])


def _depth(part, at):
    text = part.clean[part.opening:at]
    return text.count('{') - text.count('}')


def _members(body):
    """Top-level members of a record body: [(text, start, end)] relative to the body."""
    out, depth, start = [], 0, 0
    for i, ch in enumerate(body):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
        elif ch == ';' and depth == 0:
            out.append((body[start:i], start, i + 1))
            start = i + 1
    return out


def trims(source, name):
    """[(source, union name, view name)]: each overhanging view written into the union's plain array."""
    part = view(source, name)
    if not part:
        return []
    out = []
    for hit in re.finditer(r'\bunion\s*{', part.clean[:part.end]):
        if hit.start() < part.opening:
            continue
        opening = hit.end() - 1
        closing = close(part.clean, opening, '{', '}')
        if not closing:
            continue
        tail = re.match(r'\s*(' + _IDENT + r')\s*;', part.clean[closing:])
        if not tail:
            continue
        var = tail[1]
        arrays, views = {}, []
        for text, start, end in _members(part.clean[opening + 1:closing - 1]):
            plain = _ARRAY.match(text)
            if plain:
                arrays.setdefault(plain[1], (plain[2], int(plain[3])))
                continue
            record = re.match(r'\s*struct\s*{(.*)}\s*(' + _IDENT + r')\s*$', text, re.S)
            if record:
                views.append((record[2], record[1], opening + 1 + start, opening + 1 + end))
        for view_name, body, start, end in views:
            fields, offset, element = {}, 0, None
            for text, _, _ in _members(body):
                field = _ARRAY.match(text)
                scalar = re.match(r'^\s*((?:unsigned\s+|signed\s+)?' + _IDENT + r')\s+(' + _IDENT + r')\s*$', text)
                kind, field_name, count = (field[1], field[2], int(field[3])) if field else (
                    (scalar[1], scalar[2], 0) if scalar else (None, None, None))
                if kind is None or element not in (None, kind):
                    break
                element = kind
                fields[field_name] = (offset, count)
                offset += max(count, 1)
            else:
                if element not in arrays or offset <= arrays[element][1]:
                    continue
                plain_name = arrays[element][0]
                edits = [(start, end, '')]
                pattern = re.compile(r'\b' + re.escape(var) + r'\s*\.\s*' + re.escape(view_name) +
                                     r'\s*\.\s*(' + _IDENT + r')(\s*\[\s*([^\]\[]+?)\s*\])?')
                usable = True
                for use in pattern.finditer(part.clean, closing, part.end):
                    if use[1] not in fields:
                        usable = False
                        break
                    base, count = fields[use[1]]
                    if use[2]:
                        index = use[3]
                        new = '%s.%s[%s]' % (var, plain_name, str(base + int(index, 0)) if re.fullmatch(
                            r'0x[0-9a-fA-F]+|\d+', index) else '%d + (%s)' % (base, index))
                    elif count:
                        new = '(&%s.%s[%d])' % (var, plain_name, base)
                    else:
                        new = '%s.%s[%d]' % (var, plain_name, base)
                    edits.append((use.start(), use.end(), new))
                if usable and len(edits) > 1:
                    out.append(edit(source, edits))
    return out


def variants(source, name):
    """Each trim with the spill order, the trims alone, the order alone (at most LIMIT)."""
    out = []
    trimmed = trims(source, name)
    for child in trimmed:
        ordered = spill_order(child, name)
        if ordered:
            out.append((FAMILIES[0], ordered))
    out += [(FAMILIES[1], child) for child in trimmed]
    ordered = spill_order(source, name)
    if ordered:
        out.append((FAMILIES[2], ordered))
    seen, result = set(), []
    for family, text in out:
        if text not in seen:
            seen.add(text)
            result.append((family, text))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 300}  # the registry: no caller wiring (registry.py)
