"""Byte pointers read through `*(T *) (p + K)` casts, written as the records the game declared, with their literal locals.

SN64 GCC 2.8.1 (`-G0 -mips3 -O2 ... -mfp32`), a 72-instruction N64 object state handler: the saved best read its
object parameter and the player pointer (an `extern u8 *` global, copied to a local) through raw casts,
`*(s32 *) (obj + 0x88)`, `*(volatile f32 *) (p + 0xC) = f`, with three `volatile` pins that kept a load of `p + 0x10`
below two stores through `p`, and a constant local (`k = 0x8000; ... + k`) for the one value `addiu` cannot take. It
stayed at 70 through a dozen sessions (store orders, constant placements, every profile). A rewrite from the target's
assembly with the pointers typed as records (`obj->state`, `p->link = obj`) matched at once (70 -> 0): written as
members, the accesses are structure references, and the scheduler kept the load below the stores with no pin; and the
`0x8000` written as a literal put its `ori` where the target has it. Measured from the saved best, the two edits only
work together (a hypothesis about why, from the target, not read in the compiler's source):

    retype only (pins kept, k kept)       60
    literal only (raw casts)             180
    retype + literal (pins kept)           0
    retype + literal, pins dropped         0
    retype, pins dropped, k kept         745

`byte_pointer_record_view` takes every `u8 *` / `s8 *` / `char *` / `void *` pointer the source declares (the function's
parameters and locals, and `extern` globals declared in the candidate) that is read through `*(T *) (p + K)` casts,
groups pointers copied into each other (`p = D_800B3960;`), and declares one `typedef struct Rec_<function>_<pointer>`
per group, a member `m<HEX>` per offset (pointer members as `void *`), padding between them. The pointers are retyped
and each access becomes a member (a `volatile` cast stays as `*(volatile T *) &p->mK`). Children: the record with the
pins kept, with the pins dropped, and each of those with every literal local inlined (`k = 0x8000;` deleted and its one
read before the next assignment written `0x8000`, when nothing between them branches): the measured match is the last
kind, offered as one child because neither step helps alone. The saved best also passed a third argument the callee's
matched C does not take (`callee_arity_trim`'s edit, no change alone, 60); with it kept the record children are 180, so
with `callees` the same children are offered again on that family's first trimmed source (0).

Only when every other mention of a pointer is a whole value (a call argument, a stored value, a copy, a compare): no
`p + K` outside a cast, no `p[i]`, `p++` or `*p`; all casts at one offset agree (signedness included, pointers as one),
no two members overlap and every offset is a multiple of its member's size.
"""
import re

from . import callee_arity_trim
from .integer_repair_support import edit, view

FAMILY = 'byte_pointer_record_view'
FAMILIES = (FAMILY,)

SIZES = {'u8': 1, 's8': 1, 'char': 1, 'u16': 2, 's16': 2, 'short': 2, 'u32': 4, 's32': 4, 'int': 4, 'f32': 4,
         'f64': 8, 'u64': 8, 's64': 8, 'void *': 4}
BYTE_POINTER = r'(?:unsigned\s+char|signed\s+char|char|u8|s8|void)\s*\*\s*'
ACCESS = re.compile(r'\*\s*\(\s*(?P<cast>[A-Za-z_][\w\s*]*?\*)\s*\)\s*\(\s*(?P<ptr>[A-Za-z_]\w*)\s*\+\s*'
                    r'(?P<off>0[xX][0-9a-fA-F]+|\d+)\s*\)')
LITERAL = r'-?(?:0[xX][0-9a-fA-F]+|\d+)[uU]?'
LIMIT = 64


def _member_type(cast):
    """(member type, volatile) of a cast `T *`, or None: `volatile f32 *` -> f32, `u8 * volatile *` -> void *."""
    pointee = cast.strip()[:-1].strip()
    volatile = bool(re.search(r'\bvolatile\b', pointee))
    pointee = re.sub(r'\s+', ' ', re.sub(r'\bvolatile\b', ' ', pointee)).strip()
    if pointee.endswith('*'):
        return 'void *', volatile
    pointee = re.sub(r'\bconst\b', '', pointee).strip()
    return (pointee, volatile) if pointee in SIZES else None


def _declarations(source, clean, part, name):
    """{pointer: (start, end, text before the name)} of the byte pointers declared: parameters, locals, externs."""
    found = {}
    head = clean[:part.opening]
    definition = None
    for definition in re.finditer(r'\b' + re.escape(name) + r'\s*\(([^{};]*)\)\s*$', head):
        pass
    if definition:
        offset = definition.start(1)
        for piece in definition[1].split(','):
            hit = re.fullmatch(r'(\s*)(' + BYTE_POINTER + r')([A-Za-z_]\w*)\s*', piece)
            if hit:
                found[hit[3]] = (offset + len(hit[1]), offset + len(hit[1]) + len(hit[2]))
            offset += len(piece) + 1
    body = clean[part.opening + 1:part.end - 1]
    for hit in re.finditer(r'(?m)^[ \t]*(' + BYTE_POINTER + r')([A-Za-z_]\w*)\s*;', body):
        start = part.opening + 1 + hit.start(1)
        found.setdefault(hit[2], (start, start + len(hit[1])))
    for hit in re.finditer(r'(?m)^[ \t]*extern\s+(' + BYTE_POINTER + r')([A-Za-z_]\w*)\s*;', head):
        found.setdefault(hit[2], (hit.start(1), hit.end(1)))
    return found


def _groups(body, pointers):
    """Pointers copied into each other (`p = q;`) as one group each: {pointer: root}."""
    root = {p: p for p in pointers}

    def find(p):
        while root[p] != p:
            p = root[p]
        return p
    for hit in re.finditer(r'(?<![\w.>])([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\s*;', body):
        if hit[1] in root and hit[2] in root:
            root[find(hit[1])] = find(hit[2])
    return {p: find(p) for p in pointers}


def _records(source, name):
    """The retyped source (pins kept, pins dropped), or None."""
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|sizeof|typeof|__typeof__)\b', part.body):
        return None
    clean = part.clean
    declared = _declarations(source, clean, part, name)
    if not declared:
        return None
    base = part.opening + 1
    body = clean[base:part.end - 1]
    sites = {}
    for hit in ACCESS.finditer(body):
        if hit['ptr'] not in declared:
            continue
        typed = _member_type(hit['cast'])
        if typed is None:
            return None
        sites.setdefault(hit['ptr'], []).append((base + hit.start(), base + hit.end(), int(hit['off'], 0)) + typed)
    if not sites:
        return None
    group = _groups(body, list(declared))
    members = {}
    for pointer, hits in sites.items():
        table = members.setdefault(group[pointer], {})
        for _, _, offset, kind, _ in hits:
            if table.setdefault(offset, kind) != kind:
                return None
    covered = sorted((start, end) for hits in sites.values() for start, end, *_ in hits)
    retyped = {p for p in declared if group[p] in members}
    for pointer in retyped:
        for mention in re.finditer(r'(?<![\w.>])' + re.escape(pointer) + r'\b', body):
            at = base + mention.start()
            if any(a <= at < b for a, b in covered) or at == declared[pointer][1]:
                continue
            after = clean[base + mention.end():base + mention.end() + 3]
            before = clean[max(0, at - 3):at]
            if re.match(r'\s*(?:\[|\+|-(?!>)|\.)', after) or re.search(r'(?:\*|\+\+|--|&)\s*$', before):
                return None
    records, typedefs, names = {}, [], {}
    for key, table in members.items():
        if len(table) > LIMIT:
            return None
        lines, position = [], 0
        for offset in sorted(table):
            size = SIZES[table[offset]]
            if offset < position or offset % size:
                return None
            if offset > position:
                lines.append(f'    u8 pad{position:X}[0x{offset - position:X}];')
            lines.append(f'    {table[offset]} m{offset:X};')
            position = offset + size
        record = f'Rec_{name}_{key}'
        if re.search(r'\b' + re.escape(record) + r'\b', clean):
            return None
        names[key] = record
        typedefs.append(f'typedef struct {record} {{\n' + '\n'.join(lines) + f'\n}} {record};\n')
        records[key] = table
    head = clean[:part.opening]
    definition = None
    for definition in re.finditer(r'(?m)^[^\n;{}]*\b' + re.escape(name) + r'\s*\(', head):
        pass
    places = [declared[p][0] for p in retyped if declared[p][0] < part.opening]
    places.append(definition.start() if definition else part.opening)
    insert_at = clean.rfind('\n', 0, min(places)) + 1
    out = []
    for keep in (True, False):
        edits = [(insert_at, insert_at, ''.join(typedefs))]
        for pointer in retyped:
            start, end = declared[pointer]
            edits.append((start, end, names[group[pointer]] + ' *'))
        for pointer, hits in sites.items():
            for start, end, offset, kind, volatile in hits:
                member = f'{pointer}->m{offset:X}'
                if volatile and keep:
                    qualified = 'void * volatile' if kind == 'void *' else f'volatile {kind}'
                    member = f'(*({qualified} *) &{member})'
                edits.append((start, end, member))
        out.append(edit(source, edits))
    if out[0] == out[1]:
        out.pop()
    return out


def _literal_inline(source, name):
    """Every `k = LITERAL;` whose one read before k's next assignment follows in straight-line code, inlined."""
    part = view(source, name)
    if not part:
        return source
    clean = part.clean
    base = part.opening + 1
    body = clean[base:part.end - 1]
    locals_ = set(re.findall(r'(?m)^[ \t]*(?:register\s+)?(?:[su](?:8|16|32)|int|short|char|unsigned(?:\s+int)?)'
                             r'\s+([A-Za-z_]\w*)\s*;', body))
    edits = []
    for hit in re.finditer(r'(?m)^[ \t]*([A-Za-z_]\w*)\s*=\s*(' + LITERAL + r')\s*;[ \t]*\n', body):
        local, literal = hit[1], hit[2]
        if local not in locals_:
            continue
        mentions = list(re.finditer(r'(?<![\w.>])' + re.escape(local) + r'\b', body[hit.end():]))
        if not mentions:
            continue
        read = mentions[0]
        tail = body[hit.end() + read.end():]
        if re.match(r'\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|\s*(?:\+\+|--)', tail) or \
                re.search(r'(?:\+\+|--|&)\s*$', body[:hit.end() + read.start()]):
            continue
        between = body[hit.end():hit.end() + read.start()]
        if re.search(r'[{}]|\b(?:goto|while|for|do|case|default|return|switch)\b|^\s*\w+\s*:', between, re.M):
            continue
        if len(mentions) > 1 and not re.match(r'\s*=(?!=)', body[hit.end() + mentions[1].end():]):
            continue
        value = f'({literal})' if literal.startswith('-') else literal
        edits.append((base + hit.start(), base + hit.end(), ''))
        edits.append((base + hit.end() + read.start(), base + hit.end() + read.end(), value))
    return edit(source, edits) if edits else source


def _children(source, name):
    found = []
    for text in _records(source, name) or ():
        found.append(text)
        inlined = _literal_inline(text, name)
        if inlined != text:
            found.append(inlined)
    return found


def variants(source, name, callees=''):
    found = [(FAMILY, text) for text in _children(source, name)]
    if found and callees:
        # the same function also passed `t` to a callee whose matched C takes two parameters; dropping it was no
        # change alone (60) and the record children with it kept are 180: the three edits are one child
        trimmed = callee_arity_trim.variants(source, name, callees)
        if trimmed:
            found += [(FAMILY, text) for text in _children(trimmed[0][1], name)]
    return found


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'callees')}  # the registry: no caller wiring (registry.py)
