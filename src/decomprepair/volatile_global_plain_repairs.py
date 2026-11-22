"""A scalar global the draft declared `volatile` and reached through casts, as the plain global the game had.

`extern volatile unsigned short D;` and reads written `*((volatile u16 *) (&D))` are what a search leaves behind when
it needs a load to stay in program order: it works, and it hides the real shape. gcc 2.7.2 loads a volatile halfword
as `lhu` and widens it with `sll; sra` whatever the C says, so a signed read of one never produces the target's single
`lh`; and it will not move a volatile read across the volatile stores around it, while a plain read is scheduled
freely. In an N64 function that built display-list commands from a screen-size global, the plain `s16` global (read
as `D - 1` and as `D & 0x3FF`: `lh` for the first, which needs the sign, and `lhu` for the second, which combine
narrows) was one of the four changes between a draft of 1825 and the byte-identical source (declared volatile it
scored 1110 with everything else right, and as `u16` 400). The family offers the global without `volatile` and its
accesses written plainly (`volatile_global_plain`), and the same with the opposite signedness
(`volatile_global_plain_flip`). One global at a time; the judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'volatile_global_plain'
FLIP_FAMILY = 'volatile_global_plain_flip'
FAMILIES = (FAMILY, FLIP_FAMILY)
LIMIT = 6
SPELLING = r'(?:unsigned\s+(?:char|short|int)|signed\s+(?:char|short|int)|[su](?:8|16|32)|char|short|int)'
DECLARATION = re.compile(rf'(?m)^[ \t]*extern\s+(?:volatile\s+(?P<a>{SPELLING})|(?P<b>{SPELLING})\s+volatile)\s+'
                         rf'(?P<name>{IDENT})\s*;')
FLIP = {'u8': 's8', 's8': 'u8', 'u16': 's16', 's16': 'u16', 'u32': 's32', 's32': 'u32',
        'unsigned char': 'signed char', 'signed char': 'unsigned char', 'unsigned short': 'short', 'short': 'unsigned short',
        'signed short': 'unsigned short', 'unsigned int': 'int', 'int': 'unsigned int', 'signed int': 'unsigned int',
        'char': 'unsigned char'}


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    result = []
    for decl in DECLARATION.finditer(clean[:part.opening]):
        glob = decl['name']
        spelling = re.sub(r'\s+', ' ', decl['a'] or decl['b'])
        body = clean[part.opening:part.end]
        if not re.search(rf'\b{re.escape(glob)}\b', body):
            continue
        access = re.compile(rf'\*\s*\(\s*\(\s*(?:volatile\s+)?{SPELLING}\s*\*\s*\)\s*\(?\s*&\s*{re.escape(glob)}\s*\)?\s*\)')
        edits = [(part.opening + m.start(), part.opening + m.end(), glob) for m in access.finditer(body)]
        # a remaining `&glob` means the address escapes: leave volatile on
        rest = access.sub(glob, body)
        if re.search(rf'&\s*{re.escape(glob)}\b', rest):
            continue
        plain = edits + [(decl.start(), decl.end(), f'extern {spelling} {glob};')]
        result.append((FAMILY, edit(source, plain)))
        if spelling in FLIP:
            flipped = edits + [(decl.start(), decl.end(), f'extern {FLIP[spelling]} {glob};')]
            result.append((FLIP_FAMILY, edit(source, flipped)))
        if len(result) >= LIMIT:
            break
    return result
