"""A `void *` parameter m2c reads through byte offsets, written as the record the game declared.

m2c has no type for an object a function takes by pointer, so every field is `*((u16 *) (((char *) arg0) + 4))`.
The game's source read them as members (`arg0->flags`), and GCC 2.7.2 treats the two differently: a member read is
marked as part of a structure, a cast read through a char pointer is not, and sched.c lets a structure read move above
a store to a scalar global that a plain cast read cannot cross (the skill's "typed one-member field reads" note says
the opposite direction for `record_member_plain`). In a 616-instruction audio command builder the two loads after a
call went above the store of the call's result once the parameter was a record (7981 -> 7861), as the target has them.
That reading of sched.c is a hypothesis taken from the target's order, not from the compiler's source; every child is
judged.

`param_record_view` declares `typedef struct Rec_<function>_<param> {...} Rec_<function>_<param>;` before the function,
one member per distinct offset (named `m<HEX>`, typed as the casts read it, padding arrays between them), changes the
parameter's `void *` to the record pointer and each read to the member. Only when every mention of the parameter is
one of those reads or a bare argument to a call (a `volatile` read becomes `(*(volatile T *) &arg0->m38)`), all
casts at one offset agree on the type, no two members overlap and every offset is a multiple of its size."""
import re

from .csource import find
from .integer_repair_support import edit, view

FAMILY = 'param_record_view'
FAMILIES = (FAMILY,)

SIZES = {'u8': 1, 's8': 1, 'u16': 2, 's16': 2, 'u32': 4, 's32': 4, 'f32': 4, 'f64': 8}
_READ = re.compile(r'\*\s*\(\(\s*(volatile\s+)?(' + '|'.join(SIZES) + r')\s*\*\s*\)\s*\(\(\(\s*char\s*\*\s*\)\s*'
                   r'(?P<param>[A-Za-z_]\w*)\s*\)\s*\+\s*(?P<offset>0[xX][0-9a-fA-F]+|\d+)\s*\)\s*\)')
LIMIT = 48


def _parameter(source, name, part):
    """The `void *param` names of the function's parameters, with the span of each type."""
    head = source[:part.opening]
    start = head.rfind(name + '(') if (name + '(') in head else head.rfind(name)
    open_paren = head.find('(', start)
    out = []
    if open_paren < 0:
        return out
    parameters = head[open_paren + 1:head.rfind(')')]
    offset = open_paren + 1
    for piece in parameters.split(','):
        found = re.fullmatch(r'(\s*)void\s*\*\s*([A-Za-z_]\w*)(\s*)', piece)
        if found:
            out.append((found[2], offset + len(found[1]), offset + len(piece) - len(found[3])))
        offset += len(piece) + 1
    return out


def _members(part, param):
    """{offset: (type, size)} when every mention of `param` is a read at an offset or a bare call argument, else None."""
    body = part.clean[part.opening + 1:part.end - 1]
    base = part.opening + 1
    sites, members = [], {}
    covered = []
    for hit in _READ.finditer(body):
        if hit['param'] != param:
            continue
        offset = int(hit['offset'], 0)
        kind = hit[2]
        if members.setdefault(offset, kind) != kind:
            return None
        sites.append((base + hit.start(), base + hit.end(), offset, kind, bool(hit[1])))
        covered.append((hit.start(), hit.end()))
    if not sites or len(members) > LIMIT:
        return None
    for mention in re.finditer(r'(?<![\w.>])' + re.escape(param) + r'\b', body):
        if any(a <= mention.start() < b for a, b in covered):
            continue
        before = body[:mention.start()].rstrip()
        after = body[mention.end():].lstrip()
        if not (before.endswith(('(', ',')) and after.startswith((',', ')'))):
            return None  # indexed, offset, assigned or compared: not a plain record pointer
    spans = sorted((offset, offset + SIZES[kind]) for offset, kind in members.items())
    if any(offset % SIZES[kind] for offset, kind in members.items()):
        return None
    if any(spans[i][1] > spans[i + 1][0] for i in range(len(spans) - 1)):
        return None
    return members, sites


def _record(name, param, members):
    tag = f'Rec_{name}_{param}'
    lines, cursor = [], 0
    for offset in sorted(members):
        if offset > cursor:
            lines.append(f'u8 pad{cursor:X}[{offset - cursor}];')
        lines.append(f'{members[offset]} m{offset:X};')
        cursor = offset + SIZES[members[offset]]
    return tag, 'typedef struct ' + tag + ' {\n  ' + '\n  '.join(lines) + '\n} ' + tag + ';\n\n'


def variants(source, name):
    part = view(source, name)
    span = find(source, name)
    if not part or not span:
        return []
    out = []
    for param, type_start, type_end in _parameter(source, name, part)[:4]:
        found = _members(part, param)
        if not found:
            continue
        members, sites = found
        tag, typedef = _record(name, param, members)
        if re.search(r'\b' + tag + r'\b', source):
            continue
        edits = [(type_start, type_end, f'{tag} *{param}')]
        for start, end, offset, kind, volatile in sites:
            member = f'{param}->m{offset:X}'
            edits.append((start, end, f'(*(volatile {kind} *) &{member})' if volatile else member))
        text = edit(source, edits)
        shift = len(text) - len(source)
        del shift
        at = span[0]
        out.append((FAMILY, text[:at] + typedef + text[at:]))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 240}
