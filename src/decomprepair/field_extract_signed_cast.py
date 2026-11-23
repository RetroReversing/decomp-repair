"""`((word >> n) & mask)` compared with a counter, read as the signed int a narrow bit-field is.

A game that reads a 4-bit field of a packed word with a bit-field (`unsigned rows:4`) gets `lw; srl; andi` and a
signed `slt` against the loop counter: gcc 2.7.2 types a bit-field narrower than int as int, so the logical shift stays
and the comparison is signed. m2c and every search rewrite write the same read as `(word >> 12) & 0xF` on a `u32`, and the
comparison becomes unsigned (`sltu`); making the word an `s32` fixes the compare but turns the shift into `sra`. Casting
the extracted value, `(s32) ((word >> 12) & 0xF)`, gives the bit-field's `srl` + `andi` + signed compare without
inventing a struct: a 653-instruction display-list builder's row and column loops went 7012 -> 5667 together with the
other edits of that run held fixed (the same bytes as the union of two views of the word with a real bit-field).

`variants` finds each `(... >> n) & mask` (a shift of a name, field read or cast expression by a constant, then a mask of
at most 16 bits, in the function body) that sits directly beside a relational operator (`<`, `<=`, `>`, `>=`) and
offers it wrapped in `(s32)`: one child per site and one for all sites, at most 4. It only changes the type the
comparison sees; the mask keeps the value non-negative, so the result is the same for every input."""
import re

from .csource import _blank, find

FAMILY = 'field_extract_signed_cast'
FAMILIES = (FAMILY,)
LIMIT = 4
EXTRACT = re.compile(r'\(\s*\(\s*(?P<x>[^()]*(?:\([^()]*\)[^()]*)*)>>\s*(?P<n>0x[0-9a-fA-F]+|\d+)\s*\)\s*&\s*(?P<m>0x[0-9a-fA-F]+|\d+)\s*\)')
RELATION = re.compile(r'(?:<=|>=|<|>)')


def _beside_relation(clean, start, end):
    before = clean[:start].rstrip()
    after = clean[end:].lstrip()
    if re.search(r'(?:<<|>>)$', before) or re.match(r'(?:<<|>>)', after):
        return False
    return bool(RELATION.search(before[-2:]) or RELATION.match(after))


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    sites = []
    for hit in EXTRACT.finditer(clean, span[0], span[1]):
        if int(hit['m'], 0) > 0xFFFF or re.search(r'\(\s*s32\s*\)\s*$', clean[:hit.start()]):
            continue
        if re.search(r'\+\+|--|[^=!<>]=[^=]|\b[a-z_]\w*\s*\(', hit['x']) or not _beside_relation(clean, hit.start(), hit.end()):
            continue
        sites.append((hit.start(), hit.end()))
    out = []
    for start, end in sites:
        out.append(source[:start] + '(s32) ' + source[start:end] + source[end:])
    if len(sites) > 1:
        text = source
        for start, end in reversed(sites):
            text = text[:start] + '(s32) ' + text[start:end] + text[end:]
        out.append(text)
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 300}
