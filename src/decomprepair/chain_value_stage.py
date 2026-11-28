"""A compound assignment at the end of a chain, worked out in a local that the chain then stores.

    obj->r = obj->g = obj->b -= 2;          shade = obj->b - 2;
    if (obj->b < 0x20) {              ->    obj->r = obj->g = obj->b = shade;
                                            if (shade < 0x20) {

The chain's value exists only as the field's new value, so the compiler's first scheduler orders its load by the whole
chain behind it. Held in a local of the field's own type, the load keeps the order of the statements around it. On an
SN GCC 2.8.1 N64 object-update routine (263 instructions) a byte colour stepped this way was loaded ahead of an
earlier halfword in the prologue; the local, read by the test that follows too, took 1880 to about 60 together with a
case rewrite `chained_assignment_split` already offers, and the match followed. Why the local changes the order is a
hypothesis from the compiled output, not read from the compiler's source. Reading the field again in the test after
staging scored far worse (1395 against 0 on the final source), so both forms are offered.

Children (`chain_value_stage`): for each statement `a->x = a->y = b->z OP= E;` (one or more plain targets, E a literal
or a plain name) whose last target is a field with one integer type in the source: the value computed into a new local
of that type and stored by the chain; and, when the next statement or `if` condition reads the last target without
writing it or calling, the same with that read taken from the local.
"""
import re

from .integer_repair_support import IDENT, view
from .line_scan import apply, lines, relaid, with_local

FAMILY = 'chain_value_stage'
FAMILIES = (FAMILY,)
LIMIT = 12
_FIELD = rf'{IDENT}(?:(?:->|\.){IDENT})+'
_CHAIN = re.compile(rf'(?P<heads>(?:{_FIELD}\s*=\s*)+)(?P<last>{_FIELD})\s*(?P<op>[-+&|^*]|<<|>>)=\s*'
                    rf'(?P<e>-?(?:0[xX][0-9A-Fa-f]+|\d+)[uU]?|{IDENT});')
_TYPES = r'(?:u8|s8|u16|s16|u32|s32|unsigned char|signed char|unsigned short|short|unsigned int|int|char)'
_CALL = re.compile(rf'(?<![\w.>])(?!(?:if|while|sizeof)\b){IDENT}\s*\(')


def _field_type(text, field):
    """The one integer type the source's members called `field` are declared with, or None."""
    declared = re.findall(rf'(?<![\w*])({_TYPES}|[A-Za-z_]\w*\s*\*?)\s+{field}\s*(?=[;,\[:])', text)
    kinds = {' '.join(kind.split()) for kind in declared if kind not in ('return', 'goto')}
    if len(kinds) != 1:
        return None
    kind = kinds.pop()
    return kind if re.fullmatch(_TYPES, kind) else None


def _new_name(text):
    name, n = 'staged_value', 1
    while re.search(rf'\b{name}\b', text):
        n += 1
        name = f'staged_value{n}'
    return name


def _reread(following, last):
    """(start, end) inside the stripped line `following` of the part that may take the value from the local, or None."""
    if following.startswith('if ('):
        start, end = 3, following.rfind(')') + 1
    elif following.endswith(';') and not re.match(r'(?:for|while|do|switch|return|goto)\b', following):
        start, end = 0, len(following)
    else:
        return None
    part = following[start:end]
    read = rf'(?<![\w.>]){re.escape(last)}(?![\w]|\s*(?:\.|->|\[))'
    written = rf'(?:\+\+|--|&)\s*{re.escape(last)}\b|(?<![\w.>]){re.escape(last)}\s*(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=))'
    if not re.search(read, part) or re.search(written, part) or _CALL.search(part):
        return None
    return start, end


def variants(source, name):
    source = relaid(source, name)
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    out = []
    for i, line in enumerate(body):
        hit = _CHAIN.fullmatch(line.stripped)
        if not hit or (i and not body[i - 1].stripped.endswith((';', '{', '}', ':'))):
            continue
        last = hit['last']
        kind = _field_type(part.clean, re.split(r'->|\.', last)[-1])
        if not kind:
            continue
        local = _new_name(part.clean)
        # a function with no declarations of its own takes this one right after its brace
        declaration = (with_local(source, part, f'{kind} {local};')
                       or (part.opening + 1, part.opening + 1, f'\n    {kind} {local};'))
        indent = line.indent
        staged = (f'{indent}{local} = {last} {hit["op"]} {hit["e"]};\n'
                  f'{indent}{" ".join(hit["heads"].split())} {last} = {local};\n')
        edits = [declaration, (line.start, line.end, staged)]
        following = body[i + 1] if i + 1 < len(body) else None
        found = _reread(following.stripped, last) if following else None
        if found:
            start, end = found
            text = following.stripped
            read = rf'(?<![\w.>]){re.escape(last)}(?![\w])'
            changed = text[:start] + re.sub(read, local, text[start:end]) + text[end:]
            out.append((FAMILY, apply(source, edits + [(following.start, following.end,
                                                        following.indent + changed + '\n')])))
        out.append((FAMILY, apply(source, edits)))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 92}  # the registry: no caller wiring (registry.py)
