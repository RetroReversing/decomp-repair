"""A narrow struct member's signedness, taken from how the target builds the constant stored in it.

gcc stores `-1` into a `u16` field as `ori $rt, $zero, 0xFFFF` and into an `s16` field as `addiu $rt, $zero, -1`: the
same halfword in memory, a different instruction. m2c (and a hand-written struct) guesses `u16` for fields it only sees
stored, so a reset function stays one opcode off (`u8`/`s8` the same way, 0xFF against -1). A 209-instruction N64 object
reset (`gcc-2.7.2-kmc -O1`) scored 200 with `u16` fields and 0 with `s16` ones, a controlled result of one function.

When the target has `addiu $rt, $zero, -K` and the source assigns that negative literal to unsigned narrow members
(declared in a struct of this source) or through `*(u16 *)` / `*(u8 *)` casts, they are all made signed in one child,
then each alone. A multi-name declaration (`u16 a, b, c;`) is written one member a line, in the same order, so only the
assigned members change type.
"""
import re

from .csource import _blank, find

FAMILY = 'member_immediate_signedness'
FAMILIES = (FAMILY,)
LIMIT = 6

SIGNED = {'u8': 's8', 'u16': 's16', 'unsigned char': 'signed char', 'unsigned short': 'short'}
TYPE = r'(?:u8|u16|unsigned\s+char|unsigned\s+short)'
IDENT = r'[A-Za-z_]\w*'
NEGATIVE = re.compile(r'\b(?:addiu|li)\s+\$\w+\s*,\s*(?:\$(?:zero|0)\s*,\s*)?-(0x[0-9a-fA-F]+|\d+)\b')
DECLARATION = re.compile(r'(?<![\w])(?P<type>' + TYPE + r')[ \t]+(?P<names>' + IDENT + r'(?:\[\w+\])?(?:\s*,\s*'
                         + IDENT + r'(?:\[\w+\])?)*)\s*;')


def _struct_bodies(clean):
    """(start, end) of every `struct {...}` / `union {...}` body."""
    for m in re.finditer(r'\b(?:struct|union)\b[^;{}()=]*\{', clean):
        depth, at = 1, m.end()
        while at < len(clean) and depth:
            depth += {'{': 1, '}': -1}.get(clean[at], 0)
            at += 1
        if not depth:
            yield m.end(), at - 1


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    wanted = {int(value, 0) for value in NEGATIVE.findall(asm)}
    if not wanted:
        return []
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    assigned = set()
    for m in re.finditer(r'(?:->|\.)\s*(' + IDENT + r')(?:\s*\[[^\][]*\])?\s*=\s*-\s*(0x[0-9a-fA-F]+|\d+)\s*;', body):
        if int(m[2], 0) in wanted:
            assigned.add(m[1])

    # each edit is (start, end, text); one per declaration or cast
    sites = {}  # member or cast key -> [edits]
    declarations = {}
    for start, end in _struct_bodies(clean):
        for m in DECLARATION.finditer(clean, start, end):
            declarations[m.start()] = m
    for at, m in declarations.items():
        names = [item.strip() for item in m['names'].split(',')]
        for item in names:
            member = item.split('[')[0]
            if member in assigned:
                sites.setdefault(member, []).append((at, item))
    casts = []
    for m in re.finditer(r'\*\s*\(\s*\(\s*(?P<type>' + TYPE + r')\s*\*\s*\)', body):
        stop = body.find(';', m.end())
        value = re.search(r'(?<![=!<>+\-*/&|^])=\s*-\s*(0x[0-9a-fA-F]+|\d+)\s*$', body[m.end():stop])
        if stop >= 0 and value and int(value[1], 0) in wanted:
            casts.append((span[0] + m.start('type'), span[0] + m.end('type'), SIGNED[' '.join(m['type'].split())]))
    if not sites and not casts:
        return []

    def apply(members, chosen_casts):
        edits = list(chosen_casts)
        changed = {}
        for member in members:
            for at, item in sites[member]:
                changed.setdefault(at, set()).add(item)
        for at, items in changed.items():
            m = declarations[at]
            kind = ' '.join(m['type'].split())
            names = [item.strip() for item in m['names'].split(',')]
            if len(items) == len(names):
                edits.append((m.start('type'), m.end('type'), SIGNED[kind]))
                continue
            line = source.rfind('\n', 0, at) + 1
            pad = source[line:at]
            gap = '\n' + pad if not pad.strip() else ' '
            text = gap.join(f'{SIGNED[kind] if item in items else kind} {item};' for item in names)
            edits.append((at, m.end(), text))
        text = source
        for start, end, new in sorted(edits, reverse=True):
            text = text[:start] + new + text[end:]
        return text

    result = [(FAMILY, apply(list(sites), casts))]
    single = [apply([member], []) for member in sites] + [apply([], [cast]) for cast in casts]
    if len(single) > 1:
        result += [(FAMILY, text) for text in single[:LIMIT - 1]]
    return [(family, text) for family, text in dict.fromkeys(result) if text != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
