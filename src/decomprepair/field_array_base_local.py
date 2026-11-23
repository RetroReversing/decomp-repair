"""A field array's address held in a pointer local on the line before, and indexed: `hp = (s16 *)((char *)p + 0x1BC); hp[i]`.

m2c reads an array that sits in the middle of a record as one expression with the index term in the sum,
`*(s16 *)((char *)p + (i * 2) + 0x1BC)`; `deref_sum_local` keeps the sum `p + (i * 2)` in a pointer local. The game's C had
the array's own address, the record plus the field's offset, in the local and indexed it (`hp[i]`), which orders the two
registers of the sum the other way (`addu $v0, $s3, $v0` with the record first, where the index term first read
`addu $v0, $v0, $s3`) and keeps the record register from being reused. In a 443-instruction KMC gcc 2.7.2 display-state
updater (`-G0 -mips3 -mgp32 -mfp32 -O2`) it was the last row of the match (5 -> 0).

    sprintf(buf, fmt, *(s16 *)((char *)p + (i * 2) + 0x1BC));   ->   hp = (s16 *)((char *)p + 0x1BC);
                                                                    sprintf(buf, fmt, hp[i]);

The site is a dereference `*(T *)(...)` of a sum of a byte pointer `(char *)BASE`, one index term `IDX * sizeof(T)` and a
literal offset, in either order, with `T` one of `s16 u16 s32 u32 f32`; its statement is a plain one (not a loop head, not
behind an `else`). Each site gets a pointer local of `T *` declared with the function's other locals. Offered for all
sites at once and for each site alone. A candidate for the exact judge, never a verdict.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'field_array_base_local'
FAMILIES = (FAMILY,)
LIMIT = 6

IDENT = r'[A-Za-z_]\w*'
NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
SIZE = {'s16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'f32': 4, 'int': 4}
_HEAD = re.compile(rf'\*\s*\(\s*(?P<type>{"|".join(SIZE)})\s*\*\s*\)\s*\(')


def _statement_start(clean, at, opening):
    depth, start = 0, opening + 1
    for i in range(opening + 1, at):
        ch = clean[i]
        depth += (ch == '(') - (ch == ')')
        if depth == 0 and ch in ';{}':
            start = i + 1
    return start


def _parts(inner, size):
    """(base, index, offset) of `(char *)BASE + IDX * size + K` in any order of its three terms, or None."""
    terms = [t.strip() for t in re.split(r'\+(?![^()]*\))', inner)]
    if len(terms) != 3:
        return None
    base = offset = index = None
    for term in terms:
        hit = re.fullmatch(rf'\(\s*char\s*\*\s*\)\s*(?P<b>{IDENT})', term)
        if hit and base is None:
            base = hit['b']
            continue
        if re.fullmatch(NUM, term) and offset is None:
            offset = term
            continue
        hit = re.fullmatch(rf'\(?\s*(?P<i>[\w.]+)\s*\*\s*{size}\s*\)?|\(?\s*{size}\s*\*\s*(?P<j>[\w.]+)\s*\)?', term)
        if hit and index is None:
            index = hit['i'] or hit['j']
            continue
        return None
    return (base, index, offset) if None not in (base, index, offset) else None


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
    for hit in _HEAD.finditer(clean, opening, end):
        stop = close(clean, hit.end() - 1)
        if not stop:
            continue
        size = SIZE[hit['type']]
        parts = _parts(clean[hit.end():stop - 1], size)
        if not parts or re.search(rf'\b{parts[0]}\s*(?:=(?!=)|\+\+|--)', clean[hit.start():stop]):
            continue
        at = _statement_start(clean, hit.start(), opening)
        if re.search(r'\b(?:for|while|do|return|goto|else|switch|case)\b', clean[at:hit.start()]):
            continue
        sites.append((hit.start(), stop, hit['type'], parts, at))
    if not sites:
        return []

    def made(chosen):
        edits, declarations = [], ''
        for number, (start, stop, type_, (base, index, offset), at) in enumerate(chosen, 1):
            pointer = f'field{number}'
            if re.search(rf'\b{pointer}\b', clean):
                return None
            declarations += f'    {type_} *{pointer};\n'
            lead = re.match(r'\s*', source[at:]).group()
            indent = lead.rsplit('\n', 1)[-1]
            edits.append((start, stop, f'{pointer}[{index}]'))
            edits.append((at + len(lead), at + len(lead), f'{pointer} = ({type_} *)((char *){base} + {offset});\n{indent}'))
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
    return [(f, t) for f, t in result if t and t != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
