"""A pointer sum under a field access, kept in a pointer local on the line before: `p = base + i * 2;` then `*(s16 *)((char *)(p) + 0x1BC)`.

m2c writes the address of a record field in a table as one nested expression, `(*(s16 *)((char *)((base + (i * 2))) +
0x1BC))`, or as a two-dimensional cast, `((u16 (*)[0x1]) base)[i][0xde]`. The game computed the sum into a pointer of
its own (m2c names these `temp_v1_5 = base + (field * 8);` elsewhere in the same function, where it kept the
assignment). Written nested, gcc's expansion puts the scaled index first (`addu $v0, $v0, $s1`) where the assignment to
a pointer variable puts the base first (`addu $v0, $s1, $v0`), and every later use of the register differs with it; a
function with five such sums was off by that operand order in each of them, and a single one alone moves nothing the
judge can see until the others agree (`address_temporary` takes one site at a time). One child rewrites all of them.

    if ((*(s16 *)((char *)((base + (i * 2))) + 0x1BC)) < limit[i * 2]) {
->  p = base + (i * 2);
    if ((*(s16 *)((char *)(p) + 0x1BC)) < limit[i * 2]) {

The sum is a base name plus one index term scaled by a literal (no call, no assignment), its statement is a plain one
(not the head of a loop, not behind an `else`), and each site gets a pointer local of its own, declared with the
function's other locals (`void *`: the sum keeps the base's own scaling). Offered for all sites at once and for each
site alone.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'deref_sum_local'
FAMILIES = (FAMILY,)

LIMIT = 7
IDENT = r'[A-Za-z_]\w*'
NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
_SUM = re.compile(rf'^\s*\(*\s*(?P<base>{IDENT})\s*\+\s*\(\s*(?P<index>[\w ]+?)\s*\*\s*(?P<scale>{NUM})\s*\)\s*\)*\s*$')
_CAST = re.compile(r'\(\s*char\s*\*\s*\)\s*\(')
_GRID = re.compile(rf'\(\(\s*(?P<type>[su](?:8|16|32)|f32)\s*\(\s*\*\s*\)\s*\[\s*{NUM}\s*\]\s*\)\s*(?P<base>{IDENT})\s*\)'
                   rf'\s*\[\s*(?P<index>{IDENT})\s*\]\s*\[\s*(?P<offset>{NUM})\s*\]')
_SIZE = {'s8': 1, 'u8': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'f32': 4}


def _statement_start(clean, at, opening):
    depth, start = 0, opening + 1
    for i in range(opening + 1, at):
        ch = clean[i]
        depth += (ch == '(') - (ch == ')')
        if depth == 0 and ch in ';{}':
            start = i + 1
    return start


def _sites(source, clean, opening, end):
    """[(start, end, sum text, replacement template with {p})] in text order."""
    found = []
    for hit in _CAST.finditer(clean, opening, end):
        stop = close(clean, hit.end() - 1)
        if not stop:
            continue
        match = _SUM.match(clean[hit.end():stop - 1])
        if match:
            text = f"{match['base']} + ({match['index'].strip()} * {match['scale']})"
            found.append((hit.start(), stop, text, '(char *)({p})'))
    for hit in _GRID.finditer(clean, opening, end):
        size = _SIZE[hit['type']]
        offset = int(hit['offset'], 0) * size
        text = f"{hit['base']} + ({hit['index']} * {size})"
        found.append((hit.start(), hit.end(), text, f"(*({hit['type']} *)((char *)({{p}}) + 0x{offset:X}))"))
    return sorted(found)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or '#' in clean[opening:end] or re.search(r'\b(?:volatile|asm)\b', clean[opening:end]):
        return []
    sites = []
    for start, stop, text, template in _sites(source, clean, opening, end):
        at = _statement_start(clean, start, opening)
        prefix = clean[at:start]
        if re.search(r'\b(?:for|while|do|return|goto|else|switch)\b', prefix):
            continue
        sites.append((start, stop, text, template, at))
    if not sites:
        return []

    def made(chosen):
        edits, declarations = [], ''
        for number, (start, stop, text, template, at) in enumerate(chosen, 1):
            pointer = f'__repair_ptr{number}'
            declarations += f'    void *{pointer};\n'
            lead = re.match(r'\s*', source[at:]).group()
            indent = lead.rsplit('\n', 1)[-1]
            edits.append((start, stop, template.format(p=pointer)))
            edits.append((at + len(lead), at + len(lead), f'{pointer} = {text};\n{indent}'))
        text = source
        for a, b, new in sorted(edits, reverse=True):
            text = text[:a] + new + text[b:]
        head = text.index('{', span[0]) + 1
        return text[:head] + '\n' + declarations.rstrip('\n') + text[head:]

    result = []
    if len(sites) > 1:
        result.append((FAMILY, made(sites)))
    for site in sites[:LIMIT - len(result)]:
        result.append((FAMILY, made([site])))
    return [(f, t) for f, t in result if t != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
