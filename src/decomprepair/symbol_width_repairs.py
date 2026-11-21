"""The width of a symbol's accesses, back from the bytes m2c's `char` array gave them.

A draft that declares a symbol of unknown type as `extern char D_8010D784[];` (decompdecomp's refined drafts do, so
that m2c's byte offsets add up) reads and writes `*(D_8010D784 + offset)` as one byte. The target's own instructions
say how wide the accesses really are: an N64 function stored a word, `sw $s0, %lo(D_8010D784)($at)`, where the draft
had `sb`. When every instruction naming the symbol in the target's assembly has one width wider than a byte, each
`*(D + E)` becomes `*(s32 *)(D + E)` (`lw`/`sw`), `*(u16 *)` (`lhu`) or `*(s16 *)` (`lh`/`sh`). m2c's word casts
on a symbol of unknown type, `*((M2C_UNK *)((s8 *)&D + E))`, get the same treatment (`_unknown_casts`).
"""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT
from .pattern_repairs import close

FAMILY = 'symbol_access_width'
FAMILIES = (FAMILY,)
WIDTHS = {'lw': 's32', 'sw': 's32', 'lwu': 'u32', 'lh': 's16', 'lhu': 'u16', 'sh': 's16',
          'lb': 's8', 'lbu': 'u8', 'sb': 's8', 'lwc1': 'f32', 'swc1': 'f32', 'ldc1': 'f64', 'sdc1': 'f64'}


def widths(asm, symbol):
    """The C types the target's accesses to `symbol` imply, from each `%lo(symbol)` load or store."""
    found = set()
    for hit in re.finditer(r'\b(lw|sw|lwu|lh|lhu|sh|lb|lbu|sb|lwc1|swc1|ldc1|sdc1)\s+\$\w+\s*,\s*%lo\(\s*' + re.escape(symbol) + r'\s*\)', asm):
        found.add(WIDTHS[hit[1]])
    return found


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    outside = clean[:span[0]] + clean[span[1]:]
    groups = []
    for declared in re.finditer(r'(?m)^[ \t]*extern\s+char\s+(' + IDENT + r')\s*\[\s*\]\s*;', outside):
        symbol = declared[1]
        types = widths(asm, symbol)
        word = {t for t in types if t not in ('s8', 'u8')}
        if not types or len(types) != len(word):
            continue  # byte accesses too, or none: the draft's char is as good a guess as any
        kind = 'u16' if word == {'u16', 's16'} else word.pop() if len(word) == 1 else None
        if kind is None:
            continue
        edits = []
        for hit in re.finditer(r'\*\s*\(\s*' + re.escape(symbol) + r'\s*\+', clean[opening:end]):
            star = opening + hit.start()
            paren = clean.find('(', star)
            if not close(clean, paren):
                break
            edits.append((star + 1, star + 1, f'({kind} *)'))
        else:
            if edits:
                groups.append(edits)
    result = []

    def apply(chosen):
        text = source
        for at, _, insert in sorted((e for g in chosen for e in g), reverse=True):
            text = text[:at] + insert + text[at:]
        return text
    if len(groups) > 1:
        result.append((FAMILY, apply(groups)))
    result.extend((FAMILY, apply([g])) for g in groups)
    return (result + _unknown_casts(source, clean, opening, end, asm))[:6]


def _accesses(asm, symbol):
    """Each `%lo(symbol)` load or store's C type, in the target's order."""
    return [WIDTHS[hit[1]] for hit in re.finditer(r'\b(lw|sw|lwu|lh|lhu|sh|lb|lbu|sb|lwc1|swc1|ldc1|sdc1)\s+\$\w+\s*,\s*%lo\(\s*'
                                                  + re.escape(symbol) + r'\s*\)', asm)]


def _unknown_casts(source, clean, opening, end, asm):
    """m2c's reads of a symbol of unknown type, `*((M2C_UNK *)((s8 *)&D + i))`, are words; the target's own loads say
    how wide each is. An N64 sine table read with `lh`, and `lhu` where its value was negated, was 92% as words and
    exact with each read typed as the target's: in the target's order when the counts agree, else all as the most
    common width. A float table read with `lwc1` was converted from an integer until read as `f32` (95.3% -> exact)."""
    casts = list(re.finditer(r'\(\s*(M2C_UNK|' + '|'.join(sorted(set(WIDTHS.values()))) + r')\s*\*\s*\)\s*\(+\s*\(\s*s8\s*\*\s*\)\s*\(*\s*&\s*(' + IDENT + r')\b',
                             clean[opening:end]))
    result = []
    for symbol in dict.fromkeys(m[2] for m in casts):
        mine = [m for m in casts if m[2] == symbol]
        found = _accesses(asm, symbol)
        if not found or set(found) <= {'s32'}:
            continue
        # a cast that already has a real type is only wrong when the target's loads never use that width: an N64
        # function read a byte flag table as `*(s32 *)((s8 *)&D + i)` into a `u8`, which loads byte +3 (`D+0x3`,
        # a different relocation); typed `u8` it read `lbu %lo(D)`.
        if all(m[1] != 'M2C_UNK' for m in mine) and all(m[1] in found for m in mine):
            continue
        choices = []
        if len(found) == len(mine):
            choices.append(found)
        common = max(set(found), key=found.count)
        choices.append([common] * len(mine))
        for kinds in choices:
            text = source
            for m, kind in sorted(zip(mine, kinds), key=lambda p: -p[0].start()):
                at = opening + m.start(1)
                text = text[:at] + kind + text[at + len(m[1]):]
            if text != source and text not in [t for _, t in result]:
                result.append((FAMILY, text))
    return result


def guarded_indexed_variants(source, name, asm):
    """Correct a word-cast zero test when the target reads the same byte-addressed symbol."""
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    pattern = re.compile(
        r'\*\s*\(*\s*\(\s*(?P<kind>s32)\s*\*\s*\)\s*'
        r'(?P<address>\()\s*\(*\s*\(\s*(?:s8|u8|char)\s*\*\s*\)\s*\(*\s*&\s*'
        rf'(?P<symbol>{IDENT})\s*\)*\s*\+'
    )
    result = []
    for hit in pattern.finditer(clean, *span):
        end = close(clean, hit.start('address'))
        if not end or not re.match(r'\s*\)*\s*==\s*0\b', clean[end:span[1]]):
            continue
        kinds = widths(asm, hit['symbol'])
        if kinds not in ({'u8'}, {'s8'}):
            continue
        a, b = hit.span('kind')
        result.append((FAMILY, source[:a]+next(iter(kinds))+source[b:]))
        if len(result) == 2:
            break
    return result


SIGNED_HALFWORD_LOAD = 'relocated_signed_halfword_load'


def _signed_halfword_symbols(rows):
    halfword = re.compile(rf'lh (?P<operands>\$\w+, %lo\((?P<symbol>{IDENT})\)\(\$\w+\))')
    return {read['symbol'] for _, target, candidate in rows
            if (read := halfword.fullmatch(target)) and candidate == f'lw {read["operands"]}'}


def _prioritize_source_offset(part, offset):
    """Try declaring the source offset first when its initialization is independent."""
    prefix = re.compile(
        rf'\s*(?P<counter>s32\s+{IDENT}\s*=\s*0\s*;)'
        rf'\s*(?P<cursor>s16\s*\*\s*{IDENT}\s*=\s*{IDENT}\s*;)'
        rf'\s*s32\s+{offset}\s*=\s*0\s*,\s*(?P<other>{IDENT})\s*=\s*0\s*;'
    ).match(part.clean, part.opening + 1, part.end)
    if not prefix or part.source[prefix.start():prefix.end()] != prefix[0]:
        return None
    indent = re.match(r'\s*', prefix[0])[0]
    declarations = f'{indent}s32 {offset} = 0; {prefix["cursor"]} {prefix["counter"]} s32 {prefix["other"]} = 0;'
    return prefix.start(), prefix.end(), declarations


def signed_halfword_load_variants(source, name, rows):
    """Correct a measured word-to-halfword load at the same relocated address."""
    from .integer_repair_support import edit, view

    symbols = _signed_halfword_symbols(rows)
    if not symbols or not (part := view(source, name)):
        return []
    assignment = re.compile(
        rf'(?<=[;{{}}])\s*(?P<statement>{IDENT}\s*=\s*\*\s*\(\s*(?P<type>volatile\s+s32)'
        rf'\s*\*\s*\)\s*\(\s*(?P<symbol>{IDENT})\s*\+\s*(?P<offset>{IDENT})\s*\)\s*;)'
    )
    result = []
    for hit in assignment.finditer(part.clean, part.opening + 1, part.end):
        if hit['symbol'] not in symbols:
            continue
        start, end = hit.span('statement')
        if source[start:end] != hit['statement']:
            continue
        a, b = hit.span('type')
        signed = source[start:a] + 's16' + source[b:end]
        # KMC sign-extends a volatile halfword in separate instructions. The
        # one-shot scope can retain the load position with a plain signed read.
        stage = (start, end, f'do {{ {signed} }} while (0);')
        if earlier := _prioritize_source_offset(part, hit['offset']):
            result.append((SIGNED_HALFWORD_LOAD, edit(source, [earlier, stage])))
        result.append((SIGNED_HALFWORD_LOAD, edit(source, [stage])))
        result.append((SIGNED_HALFWORD_LOAD, edit(source, [(a, b, 'volatile s16')])))
    return result[:6]
