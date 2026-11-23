"""m2c's frame union (`union { ...; struct { unsigned char pad[N]; T value; } view_spXX; ... } m2c_initial_frame;`) written
as the plain locals and arrays it stands for.

When m2c cannot tell which stack slots are separate variables it declares one union over the whole frame, with one view per
slot the function touches, and every access goes through it (`m2c_initial_frame.view_sp30.value > 0.0f`,
`&m2c_initial_frame.view_sp28.value` passed to a vector helper, `(&(&m2c_initial_frame.view_sp28.value)[i]) + 0x10` for a
table of pointers above it). KMC GCC 2.7.2 keeps a union in memory, so every scalar view is a load and store the target
does not have, and no allocation or scheduling repair can reach the real code through it. A 525-instruction N64
display-list builder went from 3551 to 335 once its union, goto loops and cursor temporaries were written out by hand
(the union was the first step); this module does that step.

The rewrite: a view whose address is taken or that an indexed access lands on starts an array; the views directly after
it with the same element size become its later elements, and the array runs to the next view (one child) or covers only
those contiguous views (another child; m2c's views show which slots were touched, not how long an array was). Every other
view is a scalar local of its own type, named after its offset (`sp94`). Declarations go where the union was, in frame
order. An indexed access `((char *) (&(&U.view_X.value)[E])) + K)` becomes `((char *) &Y[E])` for the array Y that starts
`K` bytes after X, when both have the same element size. Nothing is offered when the union is read through `bytes`, a view
overlaps another one, an array would take in a view of another size, or an access has a form this does not resolve.
"""
import re

from .integer_repair_support import view
from .pattern_repairs import close

FAMILY = 'frame_view_locals'
FAMILIES = (FAMILY,)

UNION = re.compile(r'union\s*\{')
VIEW = re.compile(r'struct\s*\{\s*(?:unsigned\s+char\s+pad\[(\d+)\]\s*;\s*)?([A-Za-z_][\w\s*]*?)\s*value\s*;\s*\}\s*'
                  r'view_sp([0-9A-Fa-f]+)\s*;')
FLAT = re.compile(r'(?<![\w])([A-Za-z_][\w\s*]*?)\s*view_sp([0-9A-Fa-f]+)_value\s*;')
BYTES = re.compile(r'unsigned\s+char\s+bytes\[(\d+)\]\s*;')
SIZES = {'f32': 4, 's32': 4, 'u32': 4, 'int': 4, 'unsigned': 4, 'float': 4, 'f64': 8, 'double': 8, 's16': 2, 'u16': 2,
         'short': 2, 's8': 1, 'u8': 1, 'char': 1, 'signed char': 1, 'unsigned char': 1, 'unsigned int': 4}


def _size(kind):
    kind = ' '.join(kind.split())
    if kind.endswith('*'):
        return 4
    return SIZES.get(kind)


def _base(inner):
    """The frame offset of the union's byte 0: the offset a view's name carries minus its pad."""
    hit = VIEW.search(inner)
    return int(hit[3], 16) - int(hit[1] or 0) if hit else 0


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    found = None
    for hit in UNION.finditer(clean, part.opening + 1, part.end):
        end = close(clean, hit.end() - 1, '{', '}')
        if not end:
            return []
        after = re.match(r'\s*(m2c_initial_frame)\s*;', clean[end:])
        if after:
            found = (hit.start(), end, end + after.end(), after[1])
            break
    if not found:
        return []
    start, union_end, decl_end, frame = found
    text = clean[start:union_end]
    inner = text[text.index('{') + 1:text.rindex('}')]
    base = _base(inner)
    views = {}
    for hit in VIEW.finditer(inner):
        offset = int(hit[3], 16)
        if offset - int(hit[1] or 0) != base:
            return []
        views[offset] = ' '.join(hit[2].split())
    rest = BYTES.sub('', VIEW.sub('', inner))
    for hit in FLAT.finditer(rest):
        views[int(hit[2], 16)] = ' '.join(hit[1].split())
    if FLAT.sub('', rest).strip() or not views or any(_size(kind) is None for kind in views.values()):
        return []
    total = None
    bytes_hit = BYTES.search(inner)
    if bytes_hit:
        total = base + int(bytes_hit[1])
    order = sorted(views)
    for a, b in zip(order, order[1:]):
        if a + _size(views[a]) > b:
            return []  # overlapping views are a real union
    body_start = decl_end
    body = clean[body_start:part.end]
    access = re.compile(rf'\b{frame}\s*\.\s*view_sp([0-9A-Fa-f]+)(?:\s*\.\s*value|_value)')
    indexed = re.compile(rf'\(\s*char\s*\*\s*\)\s*\(\s*&\s*\(\s*&\s*{frame}\s*\.\s*view_sp([0-9A-Fa-f]+)\s*\.\s*value\s*\)'
                         rf'\s*\[([^\[\]]+)\]\s*\)\s*\)\s*\+\s*(0x[0-9A-Fa-f]+|\d+)')
    if re.search(rf'\b{frame}\s*\.\s*bytes\b', body):
        return []
    starts = set()
    indexed_hits = []
    for hit in indexed.finditer(body):
        x = int(hit[1], 16)
        y = x + int(hit[3], 0)
        if x not in views or y not in views or _size(views[x]) != _size(views[y]):
            return []
        starts.add(y)
        indexed_hits.append((hit, y))
    masked = indexed.sub(lambda m: ' ' * len(m.group()), body)
    for hit in access.finditer(masked):
        if int(hit[1], 16) not in views:
            return []
        before = masked[:hit.start()].rstrip()
        if before.endswith('&') and not before.endswith('&&'):
            starts.add(int(hit[1], 16))
    # every access is one of the two forms
    leftover = access.sub('', masked)
    if re.search(rf'\b{frame}\b', leftover):
        return []
    out = []
    for fill in (True, False):
        arrays = {}
        member = {}
        for offset in order:
            if offset in starts:
                arrays[offset] = 1
                member[offset] = (offset, 0)
                continue
            owner = max((o for o in arrays if o < offset), default=None)
            if owner is not None:
                size = _size(views[owner])
                last = owner + (arrays[owner] - 1) * size
                if offset == last + size and _size(views[offset]) == size and views[offset] == views[owner]:
                    arrays[owner] += 1
                    member[offset] = (owner, arrays[owner] - 1)
                    continue
            member[offset] = (offset, None)
        if fill:
            for owner in arrays:
                size = _size(views[owner])
                later = [o for o in order if o > owner and member[o][0] != owner]
                limit = later[0] if later else total
                if limit is not None:
                    arrays[owner] = max(arrays[owner], (limit - owner) // size)
        names = {o: f'sp{o:X}' for o in order}
        used = set(re.findall(r'[A-Za-z_]\w*', clean))
        if any(names[o] in used for o in order if member[o][0] == o):
            return []

        edits = []
        for hit, y in indexed_hits:
            edits.append((body_start + hit.start(), body_start + hit.end(), f'(char *) &{names[y]}[{hit[2].strip()}])'))  # the match took the `)` that closes the cast's group
        for hit in access.finditer(masked):
            offset = int(hit[1], 16)
            owner, element = member[offset]
            before = masked[:hit.start()].rstrip()
            if element == 0 and before.endswith('&') and not before.endswith('&&'):
                amp = len(before) - 1
                edits.append((body_start + amp, body_start + hit.end(), names[owner]))
                continue
            edits.append((body_start + hit.start(), body_start + hit.end(),
                          names[owner] if element is None else f'{names[owner]}[{element}]'))
        indent = re.search(r'[ \t]*$', clean[:start])[0]
        lines = []
        for offset in order:
            owner, element = member[offset]
            if owner != offset:
                continue
            kind = views[offset]
            star = ''
            while kind.endswith('*'):
                star += '*'
                kind = kind[:-1].rstrip()
            if offset in arrays:
                lines.append(f'{kind} {star}{names[offset]}[{arrays[offset]}];')
            else:
                lines.append(f'{kind} {star}{names[offset]};')
        replacement = ('\n' + indent).join(lines)
        edits.append((start, decl_end, replacement))
        edits.sort()
        text_out = source
        for a, b, new in reversed(edits):
            text_out = text_out[:a] + new + text_out[b:]
        out.append((FAMILY, text_out))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 40}  # the registry: no caller wiring (registry.py)
