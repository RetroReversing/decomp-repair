"""A narrow field's constant above the signed range, stored as the unsigned field the target stores it into.

gcc builds `0xC8` stored into an `s8` field as `addiu $rt, $zero, -0x38` (the value the signed byte holds) and into a
`u8` field as `addiu $rt, $zero, 0xC8`; a halfword `0xC800` is `-0x3800` for `s16` and `0xC800` for `u16`
(SN GCC 2.7.2 -O1: `li $2,-56` against `li $2,0x000000c8`, `li $2,-14336` against `li $2,0x0000c800`, measured by
compiling both). m2c types a field it only sees stored as `s8`/`s16`, so a function that sets a flag byte to 200
stays one instruction off. This is the positive-constant twin of `member_immediate_signedness` (which makes members
signed for a negative literal): when the target materialises a constant in 0x80..0xFF (or 0x8000..0xFFFF) and the source
assigns that value to a signed byte (halfword) it is made unsigned: `M2C_FIELD(p, s8 *, 0x17) = 0xC8;`, a store through
`*(s8 *)` / `*(s16 *)`, or a member declared `s8` / `s16` that is assigned the value. One child with every such site,
then one each (the first 6). Measured on a one-function matching case of an SN GCC 2.7.2 -O1 N64 game: the store
`M2C_FIELD(p, s8 *, 0x17) = 0xC8;` stayed one instruction off until its type was `u8`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'constant_store_unsigned'
FAMILIES = (FAMILY,)
LIMIT = 6

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'0x[0-9a-fA-F]+|\d+'
UNSIGNED = {'s8': 'u8', 's16': 'u16', 'signed char': 'u8', 'short': 'u16', 'signed short': 'u16'}
RANGE = {'s8': (0x80, 0xFF), 's16': (0x8000, 0xFFFF), 'signed char': (0x80, 0xFF), 'short': (0x8000, 0xFFFF),
         'signed short': (0x8000, 0xFFFF)}
TYPE = r'(?:s8|s16|signed\s+char|signed\s+short|short)'
POSITIVE = re.compile(r'\b(?:addiu|li|ori)\s+\$\w+\s*,\s*(?:\$(?:zero|0)\s*,\s*)?(' + NUMBER + r')\b')
MEMBER = re.compile(r'(?<![\w])(?P<type>' + TYPE + r')[ \t]+(?P<names>' + IDENT + r'(?:\[\w+\])?(?:\s*,\s*'
                    + IDENT + r'(?:\[\w+\])?)*)\s*;')


def _kind(text):
    return ' '.join(text.split())


def _fits(kind, value, wanted):
    low, high = RANGE[kind]
    return low <= value <= high and value in wanted


def _struct_bodies(clean):
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
    wanted = {int(v, 0) for v in POSITIVE.findall(asm)}
    wanted = {v for v in wanted if 0x80 <= v <= 0xFFFF}
    if not wanted:
        return []
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    value = r'(?<![=!<>+\-*/&|^])=\s*(' + NUMBER + r')\s*;'
    sites = []  # (key, [(start, end, text)])
    for m in re.finditer(r'\bM2C_FIELD\s*\(', body):
        stop = close(body, m.end() - 1)
        typed = stop and re.search(r',\s*(?P<type>' + TYPE + r')\s*\*\s*,\s*-?(?:' + NUMBER + r')\s*\)$',
                                   body[m.end():stop])
        after = stop and re.match(r'\s*' + value, body[stop:])
        if typed and after and _fits(_kind(typed['type']), int(after[1], 0), wanted):
            at = span[0] + m.end() + typed.start('type')
            sites.append((None, [(at, span[0] + m.end() + typed.end('type'), UNSIGNED[_kind(typed['type'])])]))
    for m in re.finditer(r'\*\s*\(\s*\(?\s*(?P<type>' + TYPE + r')\s*\*\s*\)', body):
        stop = body.find(';', m.end())
        after = stop >= 0 and re.search(value + r'$', body[m.end():stop + 1])
        if after and _fits(_kind(m['type']), int(after[1], 0), wanted):
            sites.append((None, [(span[0] + m.start('type'), span[0] + m.end('type'), UNSIGNED[_kind(m['type'])])]))
    assigned = {}
    for m in re.finditer(r'(?:->|\.)\s*(' + IDENT + r')(?:\s*\[[^\][]*\])?\s*' + value, body):
        assigned.setdefault(m[1], set()).add(int(m[2], 0))
    declared = {}
    for start, end in _struct_bodies(clean):
        for m in MEMBER.finditer(clean, start, end):
            names = [item.strip() for item in m['names'].split(',')]
            for item in names:
                member = item.split('[')[0]
                if any(_fits(_kind(m['type']), v, wanted) for v in assigned.get(member, ())):
                    declared.setdefault(m.start(), (m, names, set()))[2].add(item)
    for at, (m, names, items) in declared.items():
        kind = _kind(m['type'])
        if len(items) == len(names):
            edits = [(m.start('type'), m.end('type'), UNSIGNED[kind])]
        else:
            line = source.rfind('\n', 0, at) + 1
            pad = source[line:at]
            gap = '\n' + pad if not pad.strip() else ' '
            text = gap.join(f'{UNSIGNED[kind] if item in items else kind} {item};' for item in names)
            edits = [(at, m.end(), text)]
        sites.append((at, edits))
    if not sites:
        return []

    def apply(chosen):
        text = source
        for start, end, new in sorted((e for _, edits in chosen for e in edits), reverse=True):
            text = text[:start] + new + text[end:]
        return text
    result = [apply(sites)]
    if len(sites) > 1:
        result += [apply([site]) for site in sites[:LIMIT]]
    return [(FAMILY, text) for text in dict.fromkeys(result) if text != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
