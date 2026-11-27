"""m2c's range tree over `0..N` of a value tested `>= 0`, written as the `switch` with grouped cases.

    if ((kind == 0x12F) && (side >= 0)) {       if (kind == 0x12F) {
        if (side < 2) {                             switch (side) {
            A                                       case 0:
        } else {                                    case 1:
            if (side < 4) {               ->            A
                B                                       break;
            }                                       case 2:
        }                                           case 3:
    }                                                   B
                                                        break;
                                                    }
                                                }

On a `u16` index the tree compiles to `sltiu` with the `>= 0` test folded away, while the `switch` is the target's
`bltz; slti`. On a 187-instruction N64 object spawner (`sn-n64-281 -O2 -mips3`) the two trees of this shape were the
last 1000 points before its index was written as one `u16`; `embedded_if_tree_switch` does not take the guarded one.

Offered only when the meaning is unchanged: the arms hold no `break` and the guarded block holds nothing but the tree.

`variants` gives, labelled `guarded_range_switch`, one child per tree and one with all of them.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'guarded_range_switch'
FAMILIES = (FAMILY,)
LIMIT = 6
HEAD = re.compile(r'(?m)^(?P<indent>[ \t]*)if \((?:\((?P<guard>[^\n{};]+?)\) && \((?P<v1>\w+) >= 0\)|(?P<v2>\w+) >= 0)\) \{')


def _block(clean, opening):
    """(text start, text stop, index after the brace) of the block opening at `opening`."""
    end = close(clean, opening, '{', '}')
    return (opening + 1, end - 1, end) if end else None


def _tree(source, clean, head):
    var = head['v1'] or head['v2']
    outer = _block(clean, head.end() - 1)
    if not outer:
        return None
    low = re.compile(rf'\s*if \({var} < (\d+)\) \{{').match(clean, outer[0])
    first = low and _block(clean, low.end() - 1)
    other = first and re.compile(r'\s*else\s*(\{)?').match(clean, first[2])
    high = other and re.compile(rf'\s*if \({var} < (\d+)\) \{{').match(clean, other.end())
    second = high and _block(clean, high.end() - 1)
    if not second:
        return None
    rest = second[2]
    if other[1]:
        closing = re.compile(r'\s*\}').match(clean, rest)
        if not closing:
            return None
        rest = closing.end()
    if clean[rest:outer[1]].strip():
        return None
    a, b = int(low[1]), int(high[1])
    arms = [source[first[0]:first[1]], source[second[0]:second[1]]]
    if not 0 < a < b <= 16 or any(re.search(r'\bbreak\b', _blank(arm)) for arm in arms):
        return None
    pad = head['indent']
    inner = pad + ('    ' if head['guard'] else '')

    def body(arm):
        lines = [line for line in arm.split('\n') if line.strip()]
        cut = min((len(line) - len(line.lstrip()) for line in lines), default=0)
        return [f'{inner}        {line[cut:]}' for line in lines]

    lines = [f'{inner}switch ({var}) {{']
    for arm, values in zip(arms, (range(0, a), range(a, b))):
        lines += [f'{inner}    case {value}:' for value in values] + body(arm) + [f'{inner}        break;']
    lines.append(f'{inner}}}')
    if head['guard']:
        lines = [f'{pad}if ({head["guard"]}) {{', *lines, f'{pad}}}']
    return head.start(), outer[2], '\n'.join(lines)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    edits = []
    for head in HEAD.finditer(clean, opening + 1, end):
        edit = _tree(source, clean, head)
        if edit and (not edits or edit[0] >= edits[-1][1]):
            edits.append(edit)
    if not edits:
        return []

    def apply(chosen):
        text = source
        for start, stop, new in reversed(chosen):
            text = text[:start] + new + text[stop:]
        return text

    groups = [[edit] for edit in edits[:LIMIT - 1]] + ([edits] if len(edits) > 1 else [])
    return [(FAMILY, apply(group)) for group in groups]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
