"""A wide counter masked in the loop test of a guarded `do`/`while`, written as the narrow counter's `for` loop.

    i = 0;
    if ((count & 0xFFFF) != 0) {
        n = count & 0xFFFF;                  u16 i;
        do {                          ->     for (i = 0; i < (u16) count; i++) {
            BODY                                 BODY
            i++;                             }
        } while ((i & 0xFFFF) < n);

m2c (and the hand rewrites started from it) keeps gcc's rotated shape: a word counter, an entry guard and often a local
that caches the masked bound. On a 58-instruction N64 free-list function (KMC gcc 2.7.2, `-O1`) the guarded form was
60 whatever the local's type (the counter's zero went into the guard branch's delay slot, where the target has the
bound's copy) and the `for` over a `u16` counter was exact. The spelling of the bound decided it: `(u16) count`
matched where `count & 0xFFFF`, which an earlier `& 0xFFFF` of the same value can be shared with, did not (200), so both
are offered. The `u8` form is the same rule with `0xFF`; no match has needed it yet.

`masked_counter_guard_for`: offered when the guard tests the bound for non-zero (`G`, `G != 0`, `G > 0`), the block
holds only an optional `n = G;` and the `do`, the body steps the counter last and reads it only as `(i & MASK)`, the
test is `(i & MASK) < n` (or `< G`), the counter is set to 0 before the guard in the same block and used nowhere else,
`n` is read only by the test, and the body has no `continue` or `goto`. A narrow counter wraps where the word counter's
masked test also wraps, but the exact judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'masked_counter_guard_for'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
MASKS = {0xFF: 'u8', 0xFFFF: 'u16'}


def _norm(text):
    return re.sub(r'\s+', '', text)


def _bare(text):
    """`text` without spaces and without parentheses around the whole of it."""
    text = _norm(text)
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1]
    return text


def _guarded(condition):
    """The bound a non-zero guard tests."""
    text = condition.strip()
    hit = re.fullmatch(r'(.*?)\s*(?:!=|>)\s*0[uU]?', text, re.S)
    return _bare(hit[1] if hit else text)


def _test(condition, counter):
    """(mask, bound) of `[(u32)] (counter & MASK) < bound`."""
    hit = re.fullmatch(rf'\s*(?:\(\s*(?:u32|s32|int|unsigned int)\s*\)\s*)?\(\s*{counter}\s*&\s*(0x[0-9A-Fa-f]+|\d+)\s*\)'
                       r'\s*<\s*([^<>=&|?]+(?:&\s*(?:0x[0-9A-Fa-f]+|\d+)\s*\)?)?)\s*', condition)
    if not hit:
        return None, None
    return int(hit[1], 0), _bare(hit[2])


def _spellings(bound, kind, mask):
    """The bound as the loop test may spell it: a masked value also as the narrowing cast."""
    hit = re.fullmatch(r'(.+?)&(0x[0-9A-Fa-f]+|\d+)', bound)
    if hit and int(hit[2], 0) == mask and re.fullmatch(IDENT, _bare(hit[1])):
        return [f'({kind}) {_bare(hit[1])}', f'{_bare(hit[1])} & 0x{mask:X}']
    return [bound]


def _loop(source, clean, span, guard):
    """One child per bound spelling for the guard at `guard`, or nothing."""
    at = span[0] + guard.start()
    end = close(clean, span[0] + guard.end() - 1)
    if end is None:
        return []
    condition = clean[span[0] + guard.end():end - 1]
    opening = re.match(rf'\s*\{{\s*(?:({IDENT})\s*=\s*([^;{{}}]+);\s*)?do\s*\{{', clean[end:])
    if not opening:
        return []
    brace = end + opening.end() - 1
    body_end = close(clean, brace, '{', '}')
    tail = re.match(r'\s*while\s*\(', clean[body_end:]) if body_end else None
    if not tail:
        return []
    test_open = body_end + tail.end() - 1
    test_end = close(clean, test_open)
    after = re.match(r'\s*;\s*\}', clean[test_end:]) if test_end else None
    if not after:
        return []
    stop = test_end + after.end()
    if re.match(r'\s*else\b', clean[stop:]):
        return []
    inside = clean[brace + 1:body_end - 1]
    step = re.search(rf'(?<![\w.>])(?:({IDENT})\s*\+\+|\+\+\s*({IDENT})|({IDENT})\s*\+=\s*1)\s*;\s*$', inside)
    if not step or re.search(r'\b(?:continue|goto)\b', inside):
        return []
    counter = step[1] or step[2] or step[3]
    mask, bound = _test(clean[test_open + 1:test_end - 1], counter)
    if mask not in MASKS:
        return []
    kind, guarded = MASKS[mask], _guarded(condition)
    cache, value = opening[1], _bare(opening[2]) if opening[2] else None
    if cache:
        # the local caches the guarded bound and only the test reads it
        if value != guarded or bound != cache or cache == counter:
            return []
        reads = [m for m in re.finditer(rf'(?<![\w.>]){cache}\b', clean[span[0]:span[1]])]
        if len(reads) != 2 + len(re.findall(rf'\b{IDENT}\s+{cache}\s*;', clean[span[0]:at])):
            return []
    elif bound != guarded:
        return []
    declared = re.search(rf'\b(?:s32|u32|int|unsigned int|{kind})\s+({counter})\s*;', clean[span[0]:at])
    if not declared:
        return []
    zeros = list(re.finditer(rf'(?<![\w.>]){counter}\s*=\s*0\s*;', clean[span[0]:at]))
    if len(zeros) != 1:
        return []
    zero = (span[0] + zeros[0].start(), span[0] + zeros[0].end())
    between = clean[zero[1]:at]
    if between.count('{') != between.count('}') or re.search(rf'(?<![\w.>]){counter}\b', between):
        return []
    masked = rf'\(\s*{counter}\s*&\s*(?:0x{mask:X}|0x{mask:x}|{mask})\s*\)'
    body = source[brace + 1:brace + 1 + step.start()]
    if re.search(rf'(?<![\w.>]){counter}\b', re.sub(masked, '', inside[:step.start()])):
        return []
    body = re.sub(masked, counter, body).strip()
    # every use of the counter in the function is the declaration, the zero or inside this loop
    outside = clean[span[0]:zero[0]] + clean[zero[1]:at] + clean[stop:span[1]]
    if len(re.findall(rf'(?<![\w.>]){counter}\b', outside)) != 1:
        return []
    result = []
    for spelled in _spellings(guarded, kind, mask):
        loop = f'for ({counter} = 0; {counter} < ({spelled}); {counter}++) {{\n{body}\n}}'
        text = source[:zero[0]] + source[zero[1]:at] + loop + source[stop:]
        head = text[:zero[0]]
        names = (span[0] + declared.start(), span[0] + declared.end())
        head = head[:names[0]] + f'{kind} {counter};' + head[names[1]:]
        text = head + text[zero[0]:]
        if cache:
            text = text[:span[0]] + re.sub(rf'[ \t]*\b(?:s32|u32|int|unsigned int|s16|u16|u8)\s+{cache}\s*;[ \t]*\n?',
                                           '', text[span[0]:], count=1)
        result.append((FAMILY, text))
    return result


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    result = []
    for guard in re.finditer(r'\bif\s*\(', clean[span[0]:span[1]]):
        result += _loop(source, clean, span, guard)
    return result[:4]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
