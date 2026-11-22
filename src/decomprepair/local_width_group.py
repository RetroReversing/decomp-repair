"""local_width_group: locals that copy each other, narrowed to the byte (or halfword) they are cast to, together.

`local_width_repairs` narrows one word local whose uses are already cast to a narrow type. A selected-row index that
m2c spelled as two word locals (`sel = byte_from_table; ... cursor = sel; ... sel = cursor;`) is one value in the
source, and narrowing either alone is no better: in a 180-instruction menu function `u8 sel` alone scored 620 (the
loop's copy became an `andi`), `u8 cursor` alone 1490, and both 20 -> 0. A narrow local is moved with a plain `move`
where a word local needs a zero-extension, so what each copy costs depends on both ends being the same width.

Offered for a set of two or more such locals joined by plain copies (`a = b;`), each with a narrow cast of its own
somewhere in the function: all of them narrowed to the cast type the group uses (the commonest spelling, so `u8` stays
`u8`). Single locals stay `local_width_repairs`'s. Hypothesis: that a copy between two narrow locals is a plain move
and between a narrow and a word local an extension is read from the instruction diff, not from the compiler's source."""
import re

from .csource import _blank, find

FAMILY = 'local_width_group'
FAMILIES = (FAMILY,)
LIMIT = 6

IDENT = r'[A-Za-z_]\w*'
_NARROW = r'(?:s8|u8|char|signed\s+char|unsigned\s+char|s16|u16|short|unsigned\s+short)'


def _group(members, edges):
    """Connected sets of two or more members under the copy edges."""
    seen, groups = set(), []
    for start in members:
        if start in seen:
            continue
        stack, group = [start], []
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            group.append(node)
            stack += [b for a, b in edges if a == node] + [a for a, b in edges if b == node]
        if len(group) > 1:
            groups.append(sorted(group, key=members.index))
    return groups


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0 or '#' in clean[opening:span[1]] or re.search(r'\bvolatile\b', clean):
        return []
    body = clean[opening:span[1]]
    declaration = re.compile(r'(?:^|(?<=[;{}]))\s*(?P<type>s32|u32|int|unsigned\s+int)\s+(?P<name>' + IDENT + r')\s*;')
    members, casts, where = [], {}, {}
    for hit in declaration.finditer(body):
        var = hit['name']
        if re.search(r'&\s*' + re.escape(var) + r'\b', body):
            continue
        if len(re.findall(r'\b(?:s32|u32|int|unsigned\s+int|char|short|[su](?:8|16))\s+' + re.escape(var) + r'\s*[;=,]', body)) != 1:
            continue  # a name reused in an inner scope is ambiguous
        found = re.findall(r'\(\s*(' + _NARROW + r')\s*\)\s*' + re.escape(var) + r'\b', body[hit.end():])
        if not found:
            continue
        members.append(var)
        casts[var] = [re.sub(r'\s+', ' ', c) for c in found]
        where[var] = (opening + hit.start('type'), opening + hit.end('type'))
    edges = [(a, b) for a, b in re.findall(rf'(?<![\w.>])({IDENT})\s*=(?!=)\s*({IDENT})\s*;', body)
             if a in where and b in where and a != b]
    out = []
    for group in _group(members, edges):
        for kind in (('byte', ('s8', 'u8', 'char', 'signed char', 'unsigned char')),
                     ('half', ('s16', 'u16', 'short', 'unsigned short'))):
            hints = [c for var in group for c in casts[var] if c in kind[1]]
            if not hints or any(not any(c in kind[1] for c in casts[var]) for var in group):
                continue
            wanted = max(dict.fromkeys(hints), key=hints.count)
            text = source
            for var in sorted(group, key=lambda v: where[v][0], reverse=True):
                a, b = where[var]
                text = text[:a] + wanted + text[b:]
            if text != source and (FAMILY, text) not in out:
                out.append((FAMILY, text))
        if len(out) >= LIMIT:
            break
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 96}  # the registry: no caller wiring (registry.py)
