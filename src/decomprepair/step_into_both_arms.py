"""A cursor step written once in front of an `if`/`else` copied to the head of each arm.

    tri++;
    if (over && !isMA) { scale... } else { shift... }

leaves the increment before the branches (`beqz; addiu` in the delay slot). The target's `beql $s2, $zero; addiu` and a
second `addiu` in the next branch's slot are the step at the head of both arms, which reorg then takes into the slots:

    if (over && !isMA) { tri++; scale... } else { tri++; shift... }

(SN GCC 2.8.1, one N64 model loader: 460 -> exact with the other steps.) Offered only when the condition does not mention
the stepped variable, so the program is the same.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'step_into_both_arms'
FAMILIES = (FAMILY,)
LIMIT = 12

_STEP = re.compile(r'(?m)^(?P<ind>[ \t]*)(?P<step>(?P<v>[A-Za-z_]\w*)(?:\+\+|--|[ \t]*[+-]=[ \t]*\w+)[ \t]*;)[ \t]*\n(?=[ \t]*if[ \t]*\()')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    out = []
    for step in _STEP.finditer(source, source.find('{', span[0])):
        if_at = source.index('if', step.end())
        paren = source.index('(', if_at)
        paren_end = close(clean, paren, '(', ')')
        if paren_end is None or paren_end < 0 or re.search(rf"(?<![\w.>]){step['v']}\b", clean[paren:paren_end]):
            continue
        then_open = re.compile(r'\s*\{').match(clean, paren_end)
        if not then_open:
            continue
        then_end = close(clean, then_open.end() - 1, '{', '}')
        if then_end is None or then_end < 0:
            continue
        other = re.compile(r'\s*else\s*\{').match(clean, then_end)
        if not other:
            continue
        inner = '\n' + step['ind'] + '    ' + step['step']
        child = source[:step.start()] + source[step.end():then_open.end()] + inner + source[then_open.end():other.end()] + inner + source[other.end():]
        out.append((FAMILY, child))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
