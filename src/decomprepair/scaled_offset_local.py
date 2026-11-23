"""A record's byte offset, the index times a stride, computed into a local on the line before and added to the record.

m2c indexes a byte array inside a record with the product in the subscript, `((s8 *)p)[idx(x) * 8 + 0x1FF]` (or a `(char
*)p + (i * 8) + 0x1FF` sum). The game's C kept the scaled offset in a variable of its own, and that changes which operand
of the sum is first: `addu $v0, $s3, $v0` with the record register first, where the product-first expression read `addu
$v0, $v0, $s3`, and the record's register is then not tied to the product's. In a 443-instruction KMC gcc 2.7.2 display-state
updater (`-G0 -mips3 -mgp32 -mfp32 -O2`) the two such sites, one with a call in the product and one a loop variable's
product, were the rows between 270 and 5 (270 -> 5 for the pair, 5 -> 0 the last with `field_array_base_local`).

    sprintf(buf, fmt, ((s8 *)p)[idx(x) * 8 + 0x1FF]);    ->    off1 = idx(x) * 8;
                                                                sprintf(buf, fmt, *(s8 *)((char *)p + off1 + 0x1FF));

The site is `((T *)BASE)[EXPR * S + K]` for a one-byte `T` (`s8`, `u8`, `char`) or `*(T *)((char *)BASE + EXPR * S + K)`;
`EXPR` is a name, a field read or one call of names; its statement is a plain one (not a loop head, not behind an `else`)
and, when `EXPR` is a call, no other call of the statement comes before it. Each site gets an `s32` local declared with the
function's other locals; offered for all sites at once and for each site alone. A candidate for the exact judge, never a
verdict.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'scaled_offset_local'
FAMILIES = (FAMILY,)
LIMIT = 6

IDENT = r'[A-Za-z_]\w*'
NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
EXPR = rf'(?:{IDENT}\s*\([^()]*\)|[\w.]+(?:->\w+)*)'
_SUM = re.compile(rf'\*\s*\(\s*(?P<type>[su](?:8|16|32)|f32)\s*\*\s*\)\s*\(\s*\(\s*char\s*\*\s*\)\s*(?P<base>{IDENT})\s*\+\s*'
                  rf'\(?\s*(?P<expr>{EXPR})\s*\*\s*(?P<scale>{NUM})\s*\)?\s*\+\s*(?P<offset>{NUM})\s*\)')
_CALL = re.compile(rf'\b(?!(?:if|while|for|switch|sizeof|return)\b)({IDENT})\s*\(')


def _statement_start(clean, at, opening):
    depth, start = 0, opening + 1
    for i in range(opening + 1, at):
        ch = clean[i]
        depth += (ch == '(') - (ch == ')')
        if depth == 0 and ch in ';{}':
            start = i + 1
    return start


def _sites(clean, opening, end):
    found = []
    for hit in _SUM.finditer(clean, opening, end):
        found.append((hit.start(), hit.end(), hit['type'], hit['base'], hit['expr'], hit['scale'], hit['offset']))
    for hit in re.finditer(rf'\(\s*\(\s*(?P<type>s8|u8|char)\s*\*\s*\)\s*(?P<base>{IDENT})\s*\)\s*\[\s*(?P<expr>{EXPR})\s*\*\s*(?P<scale>{NUM})\s*\+\s*(?P<offset>{NUM})\s*\]', clean[opening:end]):
        found.append((opening + hit.start(), opening + hit.end(), hit['type'], hit['base'], hit['expr'], hit['scale'], hit['offset']))
    for hit in re.finditer(rf'\(\s*(?P<type>s8|u8|char)\s*\*\s*\)\s*(?P<base>{IDENT})\s*\[\s*(?P<expr>{EXPR})\s*\*\s*(?P<scale>{NUM})\s*\+\s*(?P<offset>{NUM})\s*\]', clean[opening:end]):
        found.append((opening + hit.start(), opening + hit.end(), hit['type'], hit['base'], hit['expr'], hit['scale'], hit['offset']))
    return sorted(set(found))


_BASE_LINES = re.compile(rf'(?:^[ \t]*{IDENT}\s*=\s*\(\s*[\w ]+\*\s*\)\s*\(\s*\(\s*char\s*\*\s*\)[^;\n]*;[ \t]*\n)+\Z', re.M)


def _above_base_locals(source, at):
    """The start of the run of `p = (T *)((char *)base + K);` lines just above `at` (`field_array_base_local`'s), or `at`."""
    hit = _BASE_LINES.search(source[:at].rstrip(' \t'))
    return hit.start() if hit else at


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
    for start, stop, type_, base, expr, scale, offset in _sites(clean, opening, end):
        at = _statement_start(clean, start, opening)
        if re.search(r'\b(?:for|while|do|return|goto|else|switch|case)\b', clean[at:start]):
            continue
        if re.search(rf'\b{base}\s*(?:=(?!=)|\+\+|--)', clean[start:stop]):
            continue
        calls = _CALL.findall(clean[at:start])
        if '(' in expr and len(calls) > 1:
            continue
        sites.append((start, stop, type_, base, expr.strip(), scale, offset, at))
    if not sites:
        return []

    def made(chosen, above=False):
        edits, declarations = [], ''
        for number, (start, stop, type_, base, expr, scale, offset, at) in enumerate(chosen, 1):
            local = f'off{number}'
            if re.search(rf'\b{local}\b', clean):
                return None
            declarations += f'    s32 {local};\n'
            lead = re.match(r'\s*', source[at:]).group()
            indent = lead.rsplit('\n', 1)[-1]
            edits.append((start, stop, f'*({type_} *)((char *){base} + {local} + {offset})'))
            place = _above_base_locals(source, at + len(lead)) if above else at + len(lead)
            line = f'{local} = {expr} * {scale};\n'
            edits.append((place, place, f'{indent}{line}' if above and place < at + len(lead) else f'{line}{indent}'))
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
    # a pointer local for the same statement's array (`field_array_base_local`) is read after the offset in the game's C
    # as often as before it: the offset above those lines is the other order
    for chosen in ([sites] if len(sites) > 1 else []) + [[site] for site in sites]:
        text = made(chosen, above=True)
        if text and (FAMILY, text) not in result:
            result.append((FAMILY, text))
    return [(f, t) for f, t in result if t and t != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
