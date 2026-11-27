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
`+= 1;` (or `++`) and the `copy = word & MASK;` right after, and the copy starts at the same N.

`countdown_copy_merge` is the same pair counting down, with the decrement hoisted above the body's reads:

    var_s0 = 9; ... var_v0 = 9 & 0xFFFF;             var_s0 = 9; ...
    do { a = var_v0 * 4;                             do { a = var_s0 * 4;
         var_s0 -= 1;                         ->          t[var_s0] = t[var_s0 - 1];
         t[var_v0] = t[var_v0 - 1];                       var_s0 -= 1;
         var_v0 = var_s0 & 0xFFFF;                   } while (i < var_s0);
    } while (i < (var_s0 & 0xFFFF));

The reads of the copy see the counter's old value, so they become the counter and the decrement moves to where the copy
was. A counter still declared a word is narrowed to the mask's type when every read of it is masked. An N64
shift-the-table loop (SN GCC 2.8.1, `-O2 -mips3`, 81 instructions) needed this among five steps to its exact match."""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'masked_copy_counter_merge'
COUNTDOWN = 'countdown_copy_merge'
FAMILIES = (FAMILY, COUNTDOWN)
MASKS = {'0xff': 'u8', '255': 'u8', '0xffff': 'u16', '65535': 'u16'}
WORD = r'(?:s32|u32|int|unsigned int|s16|u16|u8)'
MASK_NUMBER = r'(?:0[xX][fF]{2}(?:[fF]{2})?|255|65535)\b'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)[uU]?'


def _depth(text):
    return text.count('{') - text.count('}')


def _line(clean, start, end):
    """The whole line holding clean[start:end] when nothing else is on it."""
    a = clean.rfind('\n', 0, start) + 1
    b = clean.find('\n', end)
    b = len(clean) if b < 0 else b + 1
    return (a, b) if not (clean[a:start] + clean[end:b]).strip() else (start, end)


def _countdown(source, name):
    part = view(source, name)
    if not part or re.search(r'\bgoto\b', part.body):
        return []
    clean, out = part.clean, []
    base, end = part.opening, part.end
    for loop in re.finditer(r'\bdo\s*\{', clean[base:end]):
        brace = base + loop.end() - 1
        stop = close(clean, brace, '{', '}')
        if not stop:
            continue
        tail = re.compile(rf'(?<![\w.>])(?P<c>{IDENT})\s*=\s*(?P<w>{IDENT})(?:\s*&\s*(?P<m>{MASK_NUMBER}))?\s*;'
                          rf'(?=\s*\}}$)').search(clean, brace, stop)
        if not tail:
            continue
        c, w = tail['c'], tail['w']
        body = clean[brace:stop]
        steps = list(re.finditer(rf'(?<![\w.>]){w}\s*(?:-=\s*1\s*;|--\s*;)', body))
        if c == w or len(steps) != 1 or len(re.findall(rf'(?<![\w.>])(?:{c}|{w})\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|'
                                                      rf'(?<![\w.>]){c}\s*(?:\+\+|--)|(?:\+\+|--)\s*(?:{c}|{w})\b|'
                                                      rf'(?<![\w.>]){w}\s*\+\+|&\s*(?:{c}|{w})\b', body)) != 2:
            continue
        step_at = brace + steps[0].start()
        step_end = brace + steps[0].end()
        if (_depth(clean[brace:step_at]) != 1 or step_end > tail.start()
                or re.search(rf'(?<![\w.>]){w}\b|\b(?:break|continue)\b', clean[step_end:tail.start()])
                or not clean[:step_at].rstrip().endswith((';', '{', '}'))):
            continue
        init = re.search(rf'(?<![\w.>]){c}\s*=\s*(?P<n>{NUMBER})(?:\s*&\s*(?:{MASK_NUMBER}))?\s*;(?=\s*$)',
                         clean[base:brace - len(loop[0]) + 1])
        if not init:
            continue
        init_at, init_end = base + init.start(), base + init.end()
        writes = list(re.finditer(rf'(?<![\w.>]){w}\s*=(?!=)\s*(?P<v>[^;]*);', clean[base:init_at]))
        if not writes or not re.fullmatch(NUMBER, writes[-1]['v'].strip()) \
                or int(writes[-1]['v'].strip().rstrip('uU'), 0) != int(init['n'].rstrip('uU'), 0):
            continue
        later = re.search(rf'(?<![\w.>]){c}\b', clean[stop:end])
        if later and not re.match(rf'{c}\s*=(?!=)', clean[stop + later.start():end]):
            continue
        decl = re.search(rf'(?m)^(?P<lead>[ \t]*)(?P<type>{WORD})[ \t]+{w}[ \t]*;', clean[base:end])
        if not decl:
            continue
        mask = tail['m']
        kind = MASKS.get(mask.lower()) if mask else None
        if mask and not kind:
            continue
        if kind is None and decl['type'] not in ('u8', 'u16'):
            continue
        kind = kind or decl['type']
        edits = [(init_at, init_end, ''), (step_at, step_end, ''), (tail.start(), tail.end(), f'{w} -= 1;')]
        masked = re.compile(rf'\(\s*{w}\s*&\s*(?:{MASK_NUMBER})\s*\)|(?<![\w.>]){w}\s*&\s*(?:{MASK_NUMBER})')
        whole = [m for m in masked.finditer(clean, base, end) if not tail.start() <= m.start() < tail.end()
                 and MASKS.get(re.findall(MASK_NUMBER, m[0])[-1].lower()) == kind]
        if decl['type'] != kind:
            # every read of a word counter has to be masked, or narrowing it changes a value
            reads = [m.start() for m in re.finditer(rf'(?<![\w.>]){w}\b', clean[base:end])]
            allowed = [(m.start(), m.end()) for m in whole]
            allowed += [(step_at, step_end), (tail.start(), tail.end()), (base + decl.start(), base + decl.end())]
            allowed += [(base + m.start(), base + m.end()) for m in
                        re.finditer(rf'(?<![\w.>]){w}\s*=(?!=)\s*{NUMBER}\s*;', clean[base:end])]
            if any(not any(a <= base + at < b for a, b in allowed) for at in reads):
                continue
            edits.append((base + decl.start(), base + decl.end(), f'{decl["lead"]}{kind} {w};'))
        edits += [(m.start(), m.end(), w) for m in whole]
        edits += [(brace + m.start(), brace + m.end(), w) for m in re.finditer(rf'(?<![\w.>]){c}\b', body)
                  if not tail.start() <= brace + m.start() < tail.end()]
        if any(a < b2 and b > a2 for i, (a, b, _) in enumerate(edits) for a2, b2, _ in edits[i + 1:]):
            continue
        out.append((COUNTDOWN, edit(source, edits)))
    return out[:3]


def variants(source, name):
    return _countup(source, name) + _countdown(source, name)


def _countup(source, name):
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
