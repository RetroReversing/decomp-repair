"""Consecutive globals assigned from consecutive fields of one record, as the struct copy the game made.

`D_8011F108 = arg0->x; D_8011F10C = arg0->y; D_8011F110 = arg0->z;` comes from m2c for what the game wrote as one
assignment of a 12-byte record: its code loads the three words, takes the first global's address once
(`addiu $a2, $a2, %lo(D_8011F108)`) and stores at 0, 4 and 8 from it. As separate statements gcc addresses each
global on its own; an N64 function was 90.3% so, and exact as `*(rec *) &D_8011F108 = *(rec *) arg0;`. Offered for
two to eight word globals whose names are consecutive addresses, read from consecutive word offsets of one base, when
the target addresses the first one with `addiu` and stores through that register.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'global_record_copy'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
GLOBAL = r'D_(?P<addr>[0-9A-Fa-f]{8})'
# a word read at an offset of one base: m2c's macro, an inferred record's member, or a plain byte-offset cast
READ = (r'(?:\(\s*(?:s32|u32|f32)\s*\)\s*)?(?:'
        r'M2C_FIELD\(\s*(?P<b1>' + IDENT + r')\s*,\s*(?:s32|u32|f32)\s*\*\s*,\s*(?P<o1>0x[0-9A-Fa-f]+|\d+)\s*\)'
        r'|\(\(\s*' + IDENT + r'\s*\*\s*\)\s*(?P<b2>' + IDENT + r')\s*\)\s*->\s*field_(?P<o2>[0-9A-Fa-f]+)'
        r'|\*\s*\(\s*(?:s32|u32|f32)\s*\*\s*\)\s*\(\s*\(\s*char\s*\*\s*\)\s*\(\s*(?P<b3>' + IDENT + r')\s*\)\s*\+\s*(?P<o3>0x[0-9A-Fa-f]+|\d+)\s*\)'
        r')')
LINE = re.compile(r'(?m)^(?P<ind>[ \t]*)' + GLOBAL + r'\s*=\s*' + READ + r'\s*;[ \t]*\n')


def _read(m):
    for b, o, hexed in (('b1', 'o1', False), ('b2', 'o2', True), ('b3', 'o3', False)):
        if m[b]:
            return m[b], int(m[o], 16) if hexed else int(m[o], 0)
    return None, None


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    lines = list(LINE.finditer(clean, opening, end))
    i = 0
    while i < len(lines):
        run = [lines[i]]
        while (i + len(run) < len(lines) and lines[i + len(run)].start() == run[-1].end()
               and lines[i + len(run)]['ind'] == run[0]['ind']):
            run.append(lines[i + len(run)])
        i += len(run)
        # keep the longest prefix of consecutive addresses and offsets from one base
        base, first = _read(run[0])
        addr = int(run[0]['addr'], 16)
        good = [run[0]]
        for k, m in enumerate(run[1:], 1):
            b, off = _read(m)
            if b != base or off != first + 4 * k or int(m['addr'], 16) != addr + 4 * k:
                break
            good.append(m)
        if not 2 <= len(good) <= 8 or base is None:
            continue
        symbol = f"D_{run[0]['addr']}"
        if not re.search(r'\baddiu\s+(\$\w+)\s*,\s*\1\s*,\s*%lo\(\s*' + symbol + r'\s*\)', asm):
            continue
        typedef = f'__repair_record_copy_{len(good)}'
        start, stop = good[0].start(), good[-1].end()
        offset = f' + {first:#x}' if first else ''
        copy = (f"{good[0]['ind']}*({typedef} *) &{symbol} = "
                + (f'*({typedef} *) {base};\n' if not first else f'*({typedef} *) ((char *) {base}{offset});\n'))
        text = source[:start] + copy + source[stop:]
        decl = f'typedef struct {{ s32 w[{len(good)}]; }} {typedef};\n'
        if decl not in text:
            text = text[:span[0]] + decl + text[span[0]:]
        result.append((FAMILY, text))
    return result[:3]
