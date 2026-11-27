"""A word local that only ever holds a byte or halfword struct member (and small constants), declared that narrow.

A loop that remembers which bank, page or kind it loaded last (`if (rec.bank != last) { last = rec.bank; load(last); }`)
compiles differently when `last` is the member's type and when m2c or a rewrite declared it a word. Measured on KMC gcc
2.7.2 (`-O2 -mgp32`), in a controller pak routine: with `s32 last` the member is read straight into the comparison and
`last` is passed to the call; with `u8 last` the converted member (`andi`) is computed once, compared with `last`
unmasked and passed on, which is the target (210 -> 0). That the narrow declaration is what keeps the converted value
apart is a reading of that one compile, not of the compiler's source.

`variants` takes the member types from the structs the header and the source declare (a member name declared with two
different types is left alone) and offers, for each plain `s32`/`int` local whose every assignment is such a member or
a constant that fits, the local declared with the member's type. Locals that are stepped, compound-assigned or have
their address taken are left alone, so every value it holds is the same in the narrow type. Unsigned word locals are
left alone too: their arithmetic would turn signed."""
import re

from .csource import _blank, find
from .pattern_repairs import IDENT, close

FAMILY = 'member_width_local'
FAMILIES = (FAMILY,)
LIMIT = 4
RANGES = {'u8': (0, 0xFF), 's8': (-0x80, 0x7F), 'u16': (0, 0xFFFF), 's16': (-0x8000, 0x7FFF)}
SPELLINGS = {'u8': 'u8', 'unsigned char': 'u8', 's8': 's8', 'signed char': 's8', 'u16': 'u16', 'unsigned short': 'u16',
             's16': 's16', 'short': 's16', 'signed short': 's16'}
AGGREGATE = re.compile(rf'\b(?:struct|union)(?:\s+{IDENT})?\s*\{{')
MEMBER = re.compile(rf'(?<=[;{{}}])\s*(?P<type>[A-Za-z_][\w \t]*?)[ \t]+(?P<name>{IDENT})\s*(?=;)')
WORD = re.compile(rf'(?m)^(?P<head>[ \t]*)(?P<type>s32|int|signed int)(?P<gap>[ \t]+)'
                  rf'(?P<name>{IDENT})[ \t]*;')
ACCESS = re.compile(rf'{IDENT}(?:\s*\[[^\][;=]*\])?(?:\s*(?:\.|->)\s*{IDENT}(?:\s*\[[^\][;=]*\])?)*'
                    rf'\s*(?:\.|->)\s*(?P<member>{IDENT})')
NUMBER = re.compile(r'-?\s*(?:0[xX][0-9a-fA-F]+|\d+)[uU]?')


def member_types(text):
    """Member name -> the narrow type every struct or union in `text` declares it with (None: not one narrow type)."""
    clean = _blank(text)
    found = {}
    for aggregate in AGGREGATE.finditer(clean):
        opening = aggregate.end() - 1
        closing = close(clean, opening, '{', '}')
        if not closing:
            continue
        for member in MEMBER.finditer(clean, opening, closing):
            kind = SPELLINGS.get(' '.join(member['type'].split()))
            if found.setdefault(member['name'], kind) != kind:
                found[member['name']] = None
    return found


def _held(body, local, members):
    """The one narrow type every assignment of `local` in `body` fits, or None."""
    word = rf'\b{re.escape(local)}\b'
    if re.search(rf'(?:\+\+|--)\s*{word}|{word}\s*(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)=)|(?<!&)&\s*{word}', body):
        return None
    values = [hit[1].strip() for hit in re.finditer(rf'(?<![\w.>]){re.escape(local)}\s*=(?!=)([^;]*);', body)]
    kinds, numbers = set(), []
    for value in values:
        access = ACCESS.fullmatch(value)
        if access:
            kinds.add(members.get(access['member']))
        elif NUMBER.fullmatch(value):
            numbers.append(int(re.sub(r'[\suU]', '', value), 0))
        else:
            return None
    if len(kinds) != 1 or None in kinds:
        return None
    kind = kinds.pop()
    low, high = RANGES[kind]
    return kind if all(low <= number <= high for number in numbers) else None


def variants(source, name, header=''):
    """Proposals: one word local that only holds a narrow member, declared with the member's type."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0])
    if opening < 0:
        return []
    members = member_types(f'{header}\n;{source}')
    body = clean[opening:span[1]]
    out = []
    for declaration in WORD.finditer(clean, opening, span[1]):
        kind = _held(body, declaration['name'], members)
        if kind:
            out.append(source[:declaration.start('type')] + kind + source[declaration.end('type'):])
    return [(FAMILY, text) for text in out][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 59}
