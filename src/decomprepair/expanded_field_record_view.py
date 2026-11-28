"""Byte-offset field casts, as `M2C_FIELD` expands, written as members of a record type for each pointer.

`(*(s16 *)((char *)(arg0) + 0x6A))` is what the permuter leaves of m2c's `M2C_FIELD(arg0, s16 *, 0x6A)`, and what many
saved bests carry. `m2c_field_record_view` reads only the macro, so those sources never got the record view. The game
declared a struct, and GCC tells a member access (a structure reference) apart from a cast through a char pointer: the
scheduler may move a scalar global's load or store across the first and not the second. A pointer read from a field and
dereferenced again (`next->prev`) is a base too, and a linked list's pointers are one record.

An N64 list-node fade of 39 instructions (SN64 GCC 2.8.1) went from 675 to 105 with this view, then matched after
swapping two statements and dropping a one-shot loop and a parameter copy. That the member form lets the scheduler move
the global's address load into the branch's delay slot is read from the output, not from the compiler's source.

Children: all pointers sharing one record (when their members agree), each pointer with its own record, then each
pointer alone. Offsets are read with one type, members never overlap, and every offset is a multiple of its size.
"""
import re

from .c_scan import close
from .m2c_field_record_view import POINTER, SIZES, _definition, _record

FAMILY = 'expanded_field_record_view'
FAMILIES = (FAMILY,)
HEAD = re.compile(r'\*\s*\(\s*([A-Za-z_]\w*)\s*(\*+)\s*\)\s*\(')
SUM = re.compile(r'\s*\(\s*(?:char|u8|s8)\s*\*\s*\)\s*(.+?)\s*\+\s*(0x[0-9A-Fa-f]+|\d+)\s*', re.S)
MAX_BASES = 8


def _unwrapped(text):
    """`((p))` as `p`, with where it starts and ends inside `text`."""
    start, end = 0, len(text)
    while end - start > 1 and text[start] == '(' and close(text, start, '(', ')') == end - 1:
        start, end = start + 1, end - 1
    return start, end


def _parse(text, found):
    """`text` as a list of plain strings and accesses; each access is also appended to `found`."""
    parts, done, at = [], 0, 0
    while True:
        head = HEAD.search(text, at)
        if not head:
            break
        opening = head.end() - 1
        closing = close(text, opening, '(', ')')
        total = SUM.fullmatch(text, opening + 1, closing) if closing > 0 else None
        if not total:
            at = head.start() + 1
            continue
        start, end = _unwrapped(total[1])
        start, end = total.start(1) + start, total.start(1) + end
        base = text[start:end]
        inner = _parse(base, found)
        plain = re.fullmatch(r'[A-Za-z_]\w*', base)
        nested = len(inner) == 1 and isinstance(inner[0], dict)
        if not (plain or nested):
            at = head.start() + 1
            continue
        access = {'key': ''.join(base.split()), 'type': head[1], 'stars': head[2], 'offset': int(total[2], 0),
                  'before': text[head.start():start], 'base': inner, 'after': text[end:closing + 1]}
        found.append(access)
        parts += [text[done:head.start()], access]
        done = at = closing + 1
    parts.append(text[done:])
    return [part for part in parts if part != '']


def _render(parts, tags):
    out = []
    for part in parts:
        if isinstance(part, str):
            out.append(part)
        elif part['key'] in tags:
            out.append(f'(({tags[part["key"]]} *) {_render(part["base"], tags)})->m{part["offset"]:X}')
        else:
            out.append(part['before'] + _render(part['base'], tags) + part['after'])
    return ''.join(out)


def _layout(accesses):
    """{offset: (member type, size)} when these accesses can be one record, else None."""
    fields = {}
    for access in accesses:
        offset = access['offset']
        member, size = ('void *', POINTER) if len(access['stars']) > 1 else (access['type'], SIZES.get(access['type']))
        if size is None or offset % size or fields.setdefault(offset, (member, size)) != (member, size):
            return None
    ordered = sorted(fields.items())
    if any(at + size > later for (at, (_, size)), (later, _) in zip(ordered, ordered[1:])):
        return None
    return dict(ordered)


def variants(source, name):
    start = _definition(source, name)
    if start is None:
        return []
    found = []
    parts = _parse(source[start:], found)
    bases = {}
    for access in found:
        bases.setdefault(access['key'], []).append(access)
    layouts = {key: layout for key, accesses in bases.items() if (layout := _layout(accesses)) is not None}
    if not layouts:
        return []
    tags = {key: f'Rec_{name}_{key}' if key.isidentifier() else f'Rec_{name}_field{index}'
            for index, key in enumerate(layouts)}
    if any(re.search(r'\b' + re.escape(tag) + r'\b', source) for tag in tags.values()):
        return []
    choices = []
    shared = _layout([access for key in layouts for access in bases[key]])
    if len(layouts) > 1 and shared:
        tag = f'Rec_{name}'
        if not re.search(r'\b' + re.escape(tag) + r'\b', source):
            choices.append(({key: tag for key in layouts}, [(tag, shared)]))
    choices.append((tags, [(tags[key], layout) for key, layout in layouts.items()]))
    if len(layouts) > 1:
        choices += [({key: tags[key]}, [(tags[key], layout)]) for key, layout in list(layouts.items())[:MAX_BASES]]
    head = source[:start]
    return [(FAMILY, head + ''.join(_record(tag, fields) for tag, fields in records) + '\n' + _render(parts, chosen))
            for chosen, records in choices]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
