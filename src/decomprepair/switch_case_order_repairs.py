"""A switch's arms in the order the game's source had them, and the empty case its compare tree tests.

gcc 2.7.2 lays a small switch out as a compare tree, with the arms in source order and every value range bounded:
an N64 function tested `beq 16; slti <17; beqz; beqz 0`, a range test m2c's two cases (0 and 16) don't make. Its
source had an empty `case 17: break;` and case 16 before case 0; with both it was exact (82.4% without). Another
function matched once its arms were in the order whose layout the target has. For a switch whose arms each end in
`break` or `return` (as m2c's irregular ones do once goto_shared_tail has given each arm its tail), this offers the
arms in other orders, and each order with an empty case one above the largest.
"""
import itertools
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'switch_case_order'
FAMILIES = (FAMILY,)

LABEL = re.compile(r'(?m)^[ \t]*(?:case\s+(?P<value>[^:]+?)\s*|default\s*):')
LIMIT = 8


def _number(text):
    try:
        return int(text.strip().rstrip('uUlL'), 0)
    except ValueError:
        return None


def _arms(clean, start, end):
    """[(label text start, arm end, values)] for a switch body clean[start:end], or None when an arm falls through or
    holds a label of its own."""
    labels = [m for m in LABEL.finditer(clean, start, end) if _depth(clean, start, m.start()) == 0]
    if len(labels) < 2:
        return None
    groups = []
    i = 0
    while i < len(labels):
        first = labels[i]
        j = i
        # stacked labels (`case 1: case 2:`) belong to one arm
        while j + 1 < len(labels) and not clean[labels[j].end():labels[j + 1].start()].strip():
            j += 1
        arm_end = labels[j + 1].start() if j + 1 < len(labels) else end
        body = clean[labels[j].end():arm_end].strip()
        # each arm ends its own way out, and holds no label a goto could reach
        if not re.search(r'(?:\bbreak|\breturn\b[^;]*)\s*;$', body) or re.search(r'(?m)^[ \t]*[A-Za-z_]\w*\s*:(?!:)', body):
            return None
        values = [_number(m['value']) if m['value'] else None for m in labels[i:j + 1]]
        groups.append((first.start(), arm_end, values))
        i = j + 1
    return groups


def _depth(text, start, at):
    depth = 0
    for ch in text[start:at]:
        depth += (ch == '{') - (ch == '}')
    return depth


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    for hit in re.finditer(r'\bswitch\s*\(', clean[opening:end]):
        paren = opening + hit.end() - 1
        after = close(clean, paren)
        body_open = clean.find('{', after) if after else -1
        if body_open < 0 or clean[after:body_open].strip():
            continue
        body_close = close(clean, body_open, '{', '}')
        groups = _arms(clean, body_open + 1, body_close - 1)
        if not groups or len(groups) > 4:
            continue
        texts = [source[a:b].rstrip('\n ') + '\n' for a, b, _ in groups]
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, groups[0][0]) + 1:])[0]
        known = [v for _, _, vs in groups for v in vs if v is not None]
        extra = f'{indent}case {max(known) + 1}:\n{indent}    break;\n' if known and all(
            v is not None for _, _, vs in groups for v in vs) else None
        original = tuple(range(len(groups)))
        orders = [o for o in itertools.permutations(original) if o != original]
        candidates = []
        for order in [original] + orders:
            arms = [texts[k] for k in order]
            if order != original:
                candidates.append(arms)
            if extra:
                candidates.append(arms + [extra])
        start = source.rfind('\n', 0, groups[0][0]) + 1
        stop = source.rfind('\n', 0, body_close - 1) + 1  # the closing brace's line
        for arms in candidates[:LIMIT]:
            text = source[:start] + ''.join(arms) + source[stop:]
            if text != source and text not in [t for _, t in result]:
                result.append((FAMILY, text))
    return result
