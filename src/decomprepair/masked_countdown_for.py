"""m2c's rotated countdown over a narrow counter, written as the `for` loop it came from.

`for (j = 9; i < j; j--)` over a `u16` counter comes back from m2c as a word counter, a masked copy and the
compiler's entry test folded against the constant start:

    j = 9;                                  u16 j;
    if (i < 9U) {                           for (j = 9; i < j; j--) {
        copy = 9 & 0xFFFF;           ->         ... table[j] ... table[j - 1] ...
        do {                                }
            ... table[copy] ...
            j -= 1;
            ... table[copy - 1] ...
            copy = j & 0xFFFF;
        } while (i < (u32) (j & 0xFFFF));
    }

The copy holds the counter's value from the top of the iteration, so every read of it is the counter's before its step.
`guarded_masked_counter_for` covers the counting-up form. Offered when the guard compares with the start constant, the
body steps the counter once by one and names it nowhere else, and neither name appears outside the loop. From an N64
table insertion that shifts entries down (SN64 GCC 2.8.1, `-G0 -mips3 -O2`). Children: every such loop at once, then
each alone. The exact judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'masked_countdown_for'
FAMILIES = (FAMILY,)
LIMIT = 4
_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_HEAD = re.compile(
    rf'(?P<counter>{_ID})\s*=\s*(?P<start>{_NUM})\s*;\s*'
    rf'if\s*\(\s*(?P<bound>{_ID})\s*<\s*(?P=start)U?\s*\)\s*(?P<open>\{{)\s*'
    rf'(?P<copy>{_ID})\s*=\s*(?P=start)\s*&\s*(?P<mask>0xFFFF|0xFF)\s*;\s*do\s*(?P<do>\{{)')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0])
    if opening < 0:
        return []
    loops = []
    for hit in _HEAD.finditer(clean, opening, span[1]):
        loop = _loop(source, clean, opening, span[1], hit)
        if loop:
            loops.append(loop)
    if not loops:
        return []
    groups = [loops] + ([[one] for one in loops] if len(loops) > 1 else [])
    out = []
    for group in groups[:LIMIT]:
        edits = sorted(edit for loop in group for edit in loop)
        child = source
        for begin, end, text in reversed(edits):
            child = child[:begin] + text + child[end:]
        out.append((FAMILY, child))
    return out


def _loop(source, clean, opening, end, hit):
    """The edits that turn the loop at `hit` into a `for`, or None."""
    counter, copy, bound, mask = hit['counter'], hit['copy'], hit['bound'], hit['mask']
    guard_end = close(clean, hit.start('open'), '{', '}')
    do_end = close(clean, hit.start('do'), '{', '}')
    if not guard_end or not do_end:
        return None
    test = re.compile(rf'\s*while\s*\(\s*{bound}\s*<\s*(?:\(u32\)\s*)?\(\s*{counter}\s*&\s*{mask}\s*\)\s*\)\s*;\s*\}}').match(
        clean, do_end)
    if not test or test.end() != guard_end:
        return None
    body_start, body_end = hit.end('do'), do_end - 1
    last = re.search(rf'\n[ \t]*{copy}\s*=\s*{counter}\s*&\s*{mask}\s*;[ \t]*(?=\n[ \t]*\Z)', clean[body_start:body_end])
    if not last:
        return None
    inside = clean[body_start:body_start + last.start()]
    steps = list(re.finditer(rf'\n[ \t]*(?:{counter}\s*-=\s*1|{counter}--|--{counter})\s*;', inside))
    if len(steps) != 1 or len(re.findall(rf'\b{counter}\b', inside)) != 1:
        return None
    if re.search(rf'\b(?:{copy}|{bound})\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*(?:{copy}|{bound})\b|'
                 rf'\b(?:{copy}|{bound})\s*(?:\+\+|--)|\b(?:continue|break|goto)\b', inside):
        return None
    declarations = {}
    for local in (counter, copy):
        found = re.search(rf'(?<=[;{{}}])\n[ \t]*(?:s32|u32|int|unsigned int)\s+{local}\s*;', clean[opening:end])
        if not found:
            return None
        declarations[local] = (opening + found.start(), opening + found.end())
        spans = [declarations[local], (hit.start(), guard_end)]
        if any(not any(a <= opening + use.start() < b for a, b in spans)
               for use in re.finditer(rf'\b{local}\b', clean[opening:end])):
            return None
    a, b = declarations[counter]
    kind = 'u16' if mask == '0xFFFF' else 'u8'
    step = steps[0]
    body = source[body_start:body_start + step.start()] + source[body_start + step.end():body_start + last.start()]
    body = re.sub(rf'\b{copy}\b', counter, body)
    indent = source[source.rfind('\n', 0, hit.start()) + 1:hit.start()]
    # the body sat two blocks deep (the guard and the `do`), the `for` has one
    body = re.sub(r'(?m)^    ', '', body)
    loop = f'for ({counter} = {hit["start"]}; {bound} < {counter}; {counter}--) {{{body}\n{indent}}}'
    removed_a, removed_b = declarations[copy]
    return [(a, b, re.sub(r'(?:unsigned int|s32|u32|int)(?=\s+\w+\s*;\Z)', kind, source[a:b])),
            (removed_a, removed_b, ''), (hit.start(), guard_end, loop)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 30}
