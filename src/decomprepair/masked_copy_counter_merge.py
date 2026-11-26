"""A byte counter m2c wrote as a word counter plus a masked copy, merged into one narrow counter.

    s32 var_a0; s32 var_v0;                          u8 var_v0;
    var_v0 = 0 & 0xFF; var_a0 = 0;                   var_v0 = 0 & 0xFF;
    do { ... var_v0 ...                      ->      do { ... var_v0 ...
        var_a0 += 1; var_v0 = var_a0 & 0xFF;             var_v0 += 1;
    } while (var_v0 != 4);                           } while (var_v0 != 4);

KMC GCC 2.7.2 keeps a `u8` counter in a word register and masks it (`andi $v0,$v0,0xff`) where it is read; m2c shows the
word and the mask as two locals. `masked_counter_loop` handles the shape whose test is `(var & 0xFF) < limit` inside
an entry guard; this is the one whose test reads the copy (`copy != 4`), with no guard and often an empty `do {} while
(0)` wrapper, and the counter is read nowhere else. A byte loop with a `* 4` offset local went 200 -> 0 with the merge
alone. `masked_copy_counter_merge`. Offered when the word counter appears only in its declaration, one `= N;`, its
`+= 1;` (or `++`) and the `copy = word & MASK;` right after, and the copy starts at the same N."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'masked_copy_counter_merge'
FAMILIES = (FAMILY,)
MASKS = {'0xff': 'u8', '255': 'u8', '0xffff': 'u16', '65535': 'u16'}
WORD = r'(?:s32|u32|int|unsigned int|s16|u16|u8)'


def _line(clean, start, end):
    """The whole line holding clean[start:end] when nothing else is on it."""
    a = clean.rfind('\n', 0, start) + 1
    b = clean.find('\n', end)
    b = len(clean) if b < 0 else b + 1
    return (a, b) if not (clean[a:start] + clean[end:b]).strip() else (start, end)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, out = part.clean, []
    for step in re.finditer(rf'(?P<inc>\b(?P<w>{IDENT})\s*(?:\+=\s*1|\+\+)\s*;)\s*(?P<mask>\b(?P<c>{IDENT})\s*=\s*(?P=w)\s*&\s*'
                            rf'(?P<m>0[xX][fF]{{2}}(?:[fF]{{2}})?|255|65535)\s*;)', clean[:part.end]):
        if step.start() < part.opening:
            continue
        w, c = step['w'], step['c']
        kind = MASKS.get(step['m'].lower())
        body = clean[part.opening:part.end]
        if w == c or not kind or len(re.findall(rf'(?<![\w.>]){w}\b', body)) != 4:
            continue
        decl = re.search(rf'(?m)^[ \t]*{WORD}[ \t]+{w}[ \t]*;[ \t]*\n', body)
        init = re.search(rf'(?m)^[ \t]*{w}[ \t]*=[ \t]*(?P<n>0[xX][0-9a-fA-F]+|\d+)[ \t]*;[ \t]*\n', body)
        cdecl = re.search(rf'(?m)^(?P<lead>[ \t]*){WORD}([ \t]+){c}[ \t]*;', body)
        cinit = re.search(rf'(?<![\w.>]){c}\s*=\s*(?P<n>0[xX][0-9a-fA-F]+|\d+)(?:\s*&\s*(?:0[xX][fF]+|\d+))?\s*;', body)
        if not (decl and init and cdecl and cinit) or int(init['n'], 0) != int(cinit['n'], 0):
            continue
        base = part.opening
        edits = [(base + decl.start(), base + decl.end(), ''), (base + init.start(), base + init.end(), ''),
                 (base + cdecl.start(), base + cdecl.end(), f'{cdecl["lead"]}{kind} {c};'),
                 (step.start('inc'), step.end('mask'), f'{c} += 1;')]
        if any(a < b2 and b > a2 for i, (a, b, _) in enumerate(edits) for a2, b2, _ in edits[i + 1:]):
            continue
        out.append((FAMILY, edit(source, edits)))
    return list(dict.fromkeys(out))[:3]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
