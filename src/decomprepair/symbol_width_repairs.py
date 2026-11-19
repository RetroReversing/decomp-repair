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
          'lb': 's8', 'lbu': 'u8', 'sb': 's8'}


def widths(asm, symbol):
    """The C types the target's accesses to `symbol` imply, from each `%lo(symbol)` load or store."""
    found = set()
    for hit in re.finditer(r'\b(lw|sw|lwu|lh|lhu|sh|lb|lbu|sb)\s+\$\w+\s*,\s*%lo\(\s*' + re.escape(symbol) + r'\s*\)', asm):
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
    return [WIDTHS[hit[1]] for hit in re.finditer(r'\b(lw|sw|lwu|lh|lhu|sh|lb|lbu|sb)\s+\$\w+\s*,\s*%lo\(\s*'
                                                  + re.escape(symbol) + r'\s*\)', asm)]


def _unknown_casts(source, clean, opening, end, asm):
    """m2c's reads of a symbol of unknown type, `*((M2C_UNK *)((s8 *)&D + i))`, are words; the target's own loads say
    how wide each is. An N64 sine table read with `lh`, and `lhu` where its value was negated, was 92% as words and
    exact with each read typed as the target's: in the target's order when the counts agree, else all as the most
    common width."""
    casts = list(re.finditer(r'\(\s*M2C_UNK\s*\*\s*\)\s*\(\s*\(\s*s8\s*\*\s*\)\s*&\s*(' + IDENT + r')\b',
                             clean[opening:end]))
    result = []
    for symbol in dict.fromkeys(m[1] for m in casts):
        mine = [m for m in casts if m[1] == symbol]
        found = _accesses(asm, symbol)
        if not found or set(found) <= {'s32'}:
            continue
        choices = []
        if len(found) == len(mine):
            choices.append(found)
        common = max(set(found), key=found.count)
        choices.append([common] * len(mine))
        for kinds in choices:
            text = source
            for m, kind in sorted(zip(mine, kinds), key=lambda p: -p[0].start()):
                at = opening + m.start()
                cast = clean.find('M2C_UNK', at)
                text = text[:cast] + kind + text[cast + len('M2C_UNK'):]
            if text != source and text not in [t for _, t in result]:
                result.append((FAMILY, text))
    return result
