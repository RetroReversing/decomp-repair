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
casts at one offset agree on the type, no two members overlap and every offset is a multiple of its size.

`local_record_view` does the same for a `void *` local set from byte arithmetic (`p = (char *) tab + n * 0x50 + 0x10;`,
the assignment gets a cast to the record), and also takes `p + K` call arguments (as `&p->mK` when K is a member's
offset) and a word written at the offset of two halfwords (`*(s32 *) (p + 0x40)` beside `*(s16 *) (p + 0x40)` and
`+ 0x42`: a union of the word and the halfword pair). In the same audio command builder the command pointer typed so
went 275 -> 140: the stores to it became member stores, and the scalar global read after them moved above the
`sw $zero` the target has after it (the same sched.c hypothesis)."""
import re

from .csource import find
from .integer_repair_support import edit, view

FAMILY = 'param_record_view'
LOCAL = 'local_record_view'
FAMILIES = (FAMILY, LOCAL)

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


def _members(part, param, local=False):
    """{offset: (type, size)} when every mention of `param` is a read at an offset or a bare call argument, else None.

    For a local (`local`), its declaration, plain assignments `param = E;` and `param + K` call arguments are allowed
    too, and a word over two halfwords is kept apart in `words` (offset: (word type, low kind, high kind))."""
    body = part.clean[part.opening + 1:part.end - 1]
    base = part.opening + 1
    sites, members, words = [], {}, {}
    covered = []
    for hit in _READ.finditer(body):
        if hit['param'] != param:
            continue
        offset = int(hit['offset'], 0)
        kind = hit[2]
        if members.setdefault(offset, kind) != kind:
            if not local:
                return None
            words.setdefault(offset, set()).add(kind)
        sites.append((base + hit.start(), base + hit.end(), offset, kind, bool(hit[1])))
        covered.append((hit.start(), hit.end()))
    if not sites or len(members) > LIMIT:
        return None
    for mention in re.finditer(r'(?<![\w.>])' + re.escape(param) + r'\b', body):
        if any(a <= mention.start() < b for a, b in covered):
            continue
        before = body[:mention.start()].rstrip()
        after = body[mention.end():].lstrip()
        if before.endswith(('(', ',')) and after.startswith((',', ')')):
            continue
        if local and (re.search(r'[;{}]$', before) or not before) and re.match(r'=[^=]', after):
            continue  # its assignment
        if local and re.search(r'\*$', before) and re.match(r';', after):
            continue  # its declaration
        if local and before.endswith(('(', ',')) and re.match(r'\+\s*(?:0[xX][0-9a-fA-F]+|\d+)\s*[,)]', after):
            continue  # `param + K` passed on
        return None  # indexed, offset, assigned or compared: not a plain record pointer
    if words:
        # a word over two halfwords: the halfword pair is the member, the word a union beside it
        for offset, kinds in words.items():
            kinds.add(members[offset])
            word = [k for k in kinds if SIZES[k] == 4]
            half = [k for k in kinds if SIZES[k] == 2]
            if len(kinds) != 2 or len(word) != 1 or len(half) != 1 or offset % 4:
                return None
            high = members.get(offset + 2, half[0])
            if SIZES[high] != 2:
                return None
            members[offset] = ('union', word[0], half[0], high)
            members.pop(offset + 2, None)
    spans = sorted((offset, offset + _size(kind)) for offset, kind in members.items())
    if any(offset % _size(kind) for offset, kind in members.items()):
        return None
    if any(spans[i][1] > spans[i + 1][0] for i in range(len(spans) - 1)):
        return None
    return members, sites


def _size(kind):
    return 4 if isinstance(kind, tuple) else SIZES[kind]


def _member(param, offset, kind, members):
    """The member expression for a read of `kind` at `offset` (a union's word or halfword)."""
    if offset in members and isinstance(members[offset], tuple):
        return f'{param}->u{offset:X}.w' if SIZES[kind] == 4 else f'{param}->u{offset:X}.h.m{offset:X}'
    if offset - 2 in members and isinstance(members[offset - 2], tuple):
        return f'{param}->u{offset - 2:X}.h.m{offset:X}'
    return f'{param}->m{offset:X}'


def _record(name, param, members):
    tag = f'Rec_{name}_{param}'
    lines, cursor = [], 0
    for offset in sorted(members):
        if offset > cursor:
            lines.append(f'u8 pad{cursor:X}[{offset - cursor}];')
        kind = members[offset]
        if isinstance(kind, tuple):
            _, word, low, high = kind
            lines.append(f'union {{ {word} w; struct {{ {low} m{offset:X}; {high} m{offset + 2:X}; }} h; }} u{offset:X};')
        else:
            lines.append(f'{kind} m{offset:X};')
        cursor = offset + _size(kind)
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
        at = span[0]
        out.append((FAMILY, text[:at] + typedef + text[at:]))
    out += _locals(source, name, part, span)
    return out


def _locals(source, name, part, span):
    """`local_record_view`: each `void *` local read through byte offsets, as a record pointer."""
    out = []
    body = part.clean[part.opening + 1:part.end - 1]
    base = part.opening + 1
    for decl in list(re.finditer(r'(?<=[;{}\n])(?P<lead>\s*)void\s*\*\s*(?P<name>[A-Za-z_]\w*)\s*;', body))[:4]:
        local = decl['name']
        found = _members(part, local, local=True)
        if not found:
            continue
        members, sites = found
        tag, typedef = _record(name, local, members)
        if re.search(r'\b' + tag + r'\b', source):
            continue
        edits = [(base + decl.start('lead') + len(decl['lead']), base + decl.end(), f'{tag} *{local};')]
        for start, end, offset, kind, volatile in sites:
            member = _member(local, offset, kind, members)
            edits.append((start, end, f'(*(volatile {kind} *) &{member})' if volatile else member))
        for hit in re.finditer(r'(?<![\w.>])' + re.escape(local) + r'\s*=(?!=)\s*(?P<rhs>[^;]*);', body):
            if not re.search(r'[;{}]\s*$', body[:hit.start()]):
                continue
            rhs = (base + hit.start('rhs'), base + hit.end('rhs'))
            edits.append((rhs[0], rhs[1], f'({tag} *) ({source[rhs[0]:rhs[1]]})'))
        for hit in re.finditer(r'(?<=[(,])(?P<lead>\s*)' + re.escape(local) + r'\s*\+\s*(?P<k>0[xX][0-9a-fA-F]+|\d+)(?=\s*[,)])', body):
            k = int(hit['k'], 0)
            inside = any(k == o or (isinstance(v, tuple) and k == o + 2) for o, v in members.items())
            text = f'&{_member(local, k, "s16" if k not in members else "u8", members)}' if inside else \
                f'(char *) {local} + {hit["k"]}'
            if inside and k in members and not isinstance(members[k], tuple):
                text = f'&{local}->m{k:X}'
            edits.append((base + hit.start() + len(hit['lead']), base + hit.end(), text))
        text = edit(source, edits)
        at = span[0]
        out.append((LOCAL, text[:at] + typedef + text[at:]))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 240}
