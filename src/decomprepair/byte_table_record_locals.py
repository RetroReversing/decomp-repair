"""A byte table's records reached through address locals and an index loaded afresh, written as the record array.

m2c, and the sources searches start from it, write the stores of one record in three spellings at once:

    extern char D_80100000[];
    *((*(u8 *)((s8 *)p + 0x6E)) * 6 + D_80100000) = *(u16 *)((s8 *)p + 0);          /* a byte store: wrong width */
    temp = (u16 *)((s8 *)((*(u8 *)((s8 *)p + 0x6E)) * 6 + D_80100000) + 2);           ->  extern Row D_80100000[];
    *temp = *(u16 *)((s8 *)p + 2);                                                       D_80100000[load].m0 = ...;
    index = (*(u8 *)((s8 *)p + 0x6E)) * 6;                                               D_80100000[load].m2 = ...;
    base = D_80100000;                                                                   D_80100000[load].m4 = ...;
    *(u16 *)((s8 *)(base + index) + 4) = *(u16 *)((s8 *)p + 4);

`cast_offset_records` reads none of them: the index is itself a load, the address goes through locals, and the bare
`*(address)` of a `char` table stores one byte. Here the address locals are substituted back into their one access,
the bare access takes the width of the value it stores, the index loads are held aside while the records are built,
and the record array is declared at the table's own address.

A 59-instruction N64 function (SN GCC 2.8.1, a state switch followed by one record's three halfwords) went from 405 through 22 attempts to exact with this one rewrite; the
width of the first store alone was 405 -> 5, and no spelling of the other stores moved the last row.
"""
import re

from . import cast_offset_records
from .csource import _blank, find

FAMILY = 'byte_table_record_locals'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
_TYPE = r'(?:u8|s8|u16|s16|u32|s32|f32)'
_TABLE = re.compile(r'^[ \t]*extern[ \t]+(?:signed[ \t]+|unsigned[ \t]+)?(?:char|s8|u8)[ \t]+(' + IDENT
                    + r')[ \t]*\[[ \t]*\][ \t]*;', re.M)
_BYTE_CAST = re.compile(r'\(\s*(?:char|s8|u8)\s*\*\s*\)\s*')
_LOAD_HEAD = re.compile(r'\*\s*\(\s*(' + _TYPE + r')\s*\*\s*\)\s*\(')
_ASSIGN = re.compile(r'(?<![\w.>\]*])(' + IDENT + r')[ \t]*=(?!=)[ \t]*([^;{}=\n]+);')


def _closing(text, start):
    depth = 0
    for at in range(start, len(text)):
        depth += {'(': 1, ')': -1}.get(text[at], 0)
        if depth == 0:
            return at
    return None


def _drop_local(body, local):
    """`body` without the declaration of `local` and without a braced block that then only holds one statement."""
    return re.sub(r'(?m)^[ \t]*(?:[\w]+[ \t]+)?[\w]+[ \t]*\**[ \t]*\b' + local + r'[ \t]*;[ \t]*\n', '', body, count=1)


def _inline_pointer_locals(body, tables):
    """`t = (T *)(ADDRESS); (*t) = V;` as `*(T *)(ADDRESS) = V;` when `t` has no other use."""
    for found in list(_ASSIGN.finditer(body)):
        local, value = found[1], found[2].strip()
        cast = re.match(r'\(\s*(' + _TYPE + r')\s*\*\s*\)\s*(?=\()', value)
        if not cast or _closing(value, cast.end()) != len(value) - 1:
            continue
        if not any(re.search(r'\b' + table + r'\b', value) for table in tables):
            continue
        uses = list(re.finditer(r'\(\s*\*\s*' + local + r'\s*\)|\*\s*' + local + r'\b(?=\s*=(?!=))', body))
        if len(uses) != 1 or len(re.findall(r'\b' + local + r'\b', body)) != 3:  # declaration, set, use
            continue
        use = uses[0]
        text = body[:use.start()] + f'*({cast[1]} *){value[cast.end():]}' + body[use.end():]
        text = text.replace(found[0], '', 1)
        return _inline_pointer_locals(_drop_local(text, local), tables)
    return body


def _inline_address_locals(body, tables):
    """`base = TABLE;` and `index = load * K;` substituted into the accesses that add them, the locals removed."""
    values = {}
    for found in _ASSIGN.finditer(body):
        values.setdefault(found[1], []).append(found[2].strip())
    bases = {local: [v for v in found if v != '0'] for local, found in values.items()}
    bases = {local: found[0] for local, found in bases.items() if len(found) == 1 and found[0] in tables}
    for local, table in bases.items():
        pair = re.compile(r'\b' + local + r'[ \t]*\+[ \t]*(' + IDENT + r')\b')
        partners = set(pair.findall(body))
        if len(partners) != 1:
            continue
        index = partners.pop()
        if len(values.get(index, ())) != 1:
            continue
        summed = f'({values[index][0]}) + {table}'
        text = pair.sub(lambda _, summed=summed: summed, body)
        for gone in (local, index):
            text = re.sub(r'(?<![\w.>\]*])' + gone + r'[ \t]*=(?!=)[^;{}\n]*;[ \t]*\n?', '', text)
            text = _drop_local(text, gone)
            if re.search(r'\b' + gone + r'\b', text):
                break
        else:
            body = text
    return body


def _bare_widths(body, tables):
    """`*(ADDRESS) = *(T *)...;` through a byte table, given the width of the value it stores."""
    edits = []
    for found in re.finditer(r'(?m)^[ \t]*\*(?=\()', body):
        opening = found.end()
        closing = _closing(body, opening)
        if closing is None:
            continue
        address = body[opening:closing + 1]
        if re.match(r'\(\s*' + _TYPE + r'\s*\*', address) or not any(re.search(r'\b' + t + r'\b', address) for t in tables):
            continue
        value = re.match(r'[ \t]*=[ \t]*\(*[ \t]*(?:\([ \t]*' + _TYPE + r'[ \t]*\)[ \t]*)?\(*\*\s*\(\s*(u16|s16|u32|s32)\s*\*',
                         body[closing + 1:])
        if value:
            edits.append((opening, f'({value[1]} *)'))
    for at, cast in reversed(edits):
        body = body[:at] + cast + body[at:]
    return body


def _hold_loads(body):
    """Every load `*(T *)(...)` that scales into an address, as an opaque name; (body, {name: load})."""
    held = {}
    at = 0
    while True:
        found = _LOAD_HEAD.search(body, at)
        if not found:
            return body, held
        closing = _closing(body, found.end() - 1)
        if closing is None:
            return body, held
        start, stop = found.start(), closing + 1
        # the parenthesis m2c puts around a load
        while start and body[start - 1] == '(' and stop < len(body) and body[stop] == ')':
            start, stop = start - 1, stop + 1
        if re.match(r'[ \t]*\)?[ \t]*(?:\*|<<)[ \t]*(?:0x[0-9A-Fa-f]+|\d+)', body[stop:]):
            text = body[found.start():closing + 1]
            label = next((n for n, load in held.items() if load == text), f'__load{len(held)}')
            held[label] = text
            body = body[:start] + label + body[stop:]
            at = start + len(label)
        else:
            at = found.end()


def _plain_addresses(body, tables):
    """The `(s8 *)` casts removed inside accesses through a byte table (byte arithmetic either way)."""
    pieces, at = [], 0
    for found in re.finditer(r'\*\s*\(\s*' + _TYPE + r'\s*\*\s*\)\s*(?=\()', body):
        if found.start() < at:
            continue
        closing = _closing(body, found.end())
        if closing is None:
            continue
        address = body[found.end():closing + 1]
        if any(re.search(r'\b' + t + r'\b', address) for t in tables):
            pieces.append(body[at:found.end()] + _BYTE_CAST.sub('', address))
            at = closing + 1
    return ''.join(pieces) + body[at:]


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    head = source[:span[0]]
    tables = [t for t in _TABLE.findall(_blank(head)) if not re.search(r'\b' + t + r'\b', _blank(header))]
    if not tables:
        return []
    body = source[span[0]:span[1]]
    if '__load' in body:
        return []
    body = _inline_pointer_locals(body, tables)
    body = _inline_address_locals(body, tables)
    body = _bare_widths(body, tables)
    body, held = _hold_loads(body)
    body = _plain_addresses(body, tables)
    if not held:
        return []
    out = []
    for family, text in cast_offset_records.variants(head + body + source[span[1]:], name, header)[:2]:
        used = [t for t in tables if f'extern {cast_offset_records.TAG}_{t}Table {t};' in text
                or f'{cast_offset_records.TAG}_{t} ' in text]
        if family != cast_offset_records.FAMILY or not used:
            continue
        for table in used:
            # the records at the table's own address: `extern Row TABLE[];`
            tag = f'{cast_offset_records.TAG}_{table}'
            whole = re.compile(r'typedef struct \{\n    ' + tag + r' rows\[1\];\n\} ' + tag + r'Table;\nextern ' + tag
                               + r'Table ' + table + r';\n')
            if whole.search(text):
                text = whole.sub(f'extern {tag} {table}[];\n', text)
                text = re.sub(r'\b' + table + r'\.rows\[', f'{table}[', text)
        for label, load in held.items():
            text = text.replace(label, f'({load})')
        text = re.sub(r'(?m)^[ \t]+\n(?=[ \t]*\n)', '', text)
        if (FAMILY, text) not in out:
            out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
