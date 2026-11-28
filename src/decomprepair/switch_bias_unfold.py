"""A `switch` on a biased copy of a value, written on the value itself with its labels raised.

m2c reads the jump-table index off the register that already has the bias taken away and names it:

    var_v1 = type - 1;                      if (type == 0x11) {
    if (type == 0x11) {                         type = roll(0x11);
        type = ...;                  ->     }
        var_v1 = type - 1;                  switch (type) {
    }                                       case 1:
    switch (var_v1) {                       case 6:
    case 0:
    case 5:

The compiler made that subtraction itself (`addiu $v1, $a0, -1` in the branch's delay slot, copied to each path); a
local of the source's own takes another register and a move the target does not have. On a 229-instruction SN GCC 2.8.1
N64 pickup update, part of a chain to exact: with this step left out the rest stood at 310.

Offered when every mention of the local is `local = value - K;` (one `value`, one `K`), the one `switch (local)` and
its declaration, and every assignment of `value` from the first of those onward is followed at once by the local's
assignment or comes before it with nothing between that reads the local. `switch_offset_table` is the opposite edit.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'switch_bias_unfold'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'


def _labels(clean, start, end):
    """The `case` constants of the switch body clean[start:end] itself, not of a switch inside it."""
    inner = []
    for nested in re.finditer(r'\bswitch\s*\(', clean[start:end]):
        opened = clean.find('{', start + nested.end(), end)
        shut = close(clean, opened, '{', '}') if opened >= 0 else None
        if shut:
            inner.append((opened, shut))
    found = []
    for case in re.finditer(r'\bcase\s+([^:]+?)\s*:', clean[start:end]):
        at = start + case.start()
        if any(a <= at < b for a, b in inner):
            continue
        value = re.fullmatch(r'-?' + NUMBER, case[1])
        if not value:
            return None
        found.append((start + case.start(1), start + case.end(1), int(case[1], 0)))
    return found


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    body = clean.find('{', span[0], span[1])
    if body < 0:
        return []
    result = []
    for switch in re.finditer(r'\bswitch\s*\(\s*(' + IDENT + r')\s*\)\s*\{', clean[body:span[1]]):
        local = switch[1]
        opened = body + switch.end() - 1
        shut = close(clean, opened, '{', '}')
        sets = list(re.finditer(r'(?m)(?<![\w.>])' + local + r'\s*=\s*(' + IDENT + r')\s*-\s*(' + NUMBER + r')\s*;[ \t]*\n?',
                                clean[body:span[1]]))
        declared = re.search(r'(?m)^[ \t]*(?:s32|u32|int|unsigned(?:\s+int)?)\s+' + local + r'\s*;[ \t]*\n', clean[body:span[1]])
        mentions = len(re.findall(r'(?<![\w.>])' + local + r'\b', clean[body:span[1]]))
        if not shut or not sets or not declared or mentions != len(sets) + 2:
            continue
        values = {(m[1], int(m[2], 0)) for m in sets}
        if len(values) != 1:
            continue
        value, bias = next(iter(values))
        if not bias or value == local or any(body + m.start() > opened for m in sets):
            continue
        # the value must not change after the last copy of it without another copy following
        written = r'(?<![\w.>])' + value + r'\s*(?:(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+|--)'
        between = clean[body + sets[0].end():opened]
        if any(not re.match(r'[^;{}]*;\s*' + local + r'\s*=', between[w.start():]) for w in re.finditer(written, between)):
            continue
        cases = _labels(clean, opened, shut)
        if not cases:
            continue
        edits = [(body + m.start(), body + m.end(), '') for m in sets]
        edits.append((body + declared.start(), body + declared.end(), ''))
        at = body + switch.start()
        edits.append((at + clean[at:opened].index(local), at + clean[at:opened].index(local) + len(local), value))
        edits += [(start, end, str(number + bias)) for start, end, number in cases]
        child = source
        for start, end, text in sorted(edits, reverse=True):
            child = child[:start] + text + child[end:]
        result.append((FAMILY, child))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
