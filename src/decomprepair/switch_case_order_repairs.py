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
from .goto_structure_repairs import parse
from .pattern_repairs import close

FAMILY = 'switch_case_order'
LOCAL_LABEL_FAMILY = 'switch_case_local_label_order'
FAMILIES = (FAMILY, LOCAL_LABEL_FAMILY)

LABEL = re.compile(r'(?m)^[ \t]*(?:case\s+(?P<value>[^:]+?)\s*|default\s*):')
LIMIT = 8
_NAMED_LABEL = re.compile(r'(?m)(?:^|(?<=[;{}:]))\s*([A-Za-z_]\w*)\s*:(?!:)')
_GOTO = re.compile(r'\bgoto\s+([A-Za-z_]\w*)\s*;')


def _number(text):
    try:
        return int(text.strip().rstrip('uUlL'), 0)
    except ValueError:
        return None


def _labels_are_internal(body, arm_start, arm_end, jumps):
    labels = {m[1] for m in _NAMED_LABEL.finditer(body) if m[1] != 'default'}
    if not labels:
        return True
    try:
        last = parse(body, 0, len(body))[-1]
    except ValueError:
        return False
    if not re.fullmatch(r'(?:break|return\b[^;]*)\s*;', body[last.start:last.end], re.S):
        return False
    return all(jumps.get(label) and all(arm_start <= pos < arm_end for pos in jumps[label])
               for label in labels)


def _arms(clean, start, end, jumps):
    """[(label text start, arm end, values)] for a switch body clean[start:end], or None when an arm falls through or
    has a label reachable from outside the arm."""
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
        # Each arm has its own exit. Any shared tail label must stay private
        # to that arm, so a jump from elsewhere cannot use its old placement.
        if (not re.search(r'(?:\bbreak|\breturn\b[^;]*)\s*;$', body)
                or not _labels_are_internal(body, labels[j].end(), arm_end, jumps)):
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
    if re.search(r'\bgoto\s*\*', clean[opening:end]):
        return []
    jumps = {}
    for jump in _GOTO.finditer(clean, opening, end):
        jumps.setdefault(jump[1], []).append(jump.start())
    labelled, result = [], []
    for hit in re.finditer(r'\bswitch\s*\(', clean[opening:end]):
        paren = opening + hit.end() - 1
        after = close(clean, paren)
        body_open = clean.find('{', after) if after else -1
        if body_open < 0 or clean[after:body_open].strip():
            continue
        body_close = close(clean, body_open, '{', '}')
        groups = _arms(clean, body_open + 1, body_close - 1, jumps)
        if not groups or len(groups) > 4:
            continue
        texts = [source[a:b].rstrip('\n ') + '\n' for a, b, _ in groups]
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, groups[0][0]) + 1:])[0]
        known = [v for _, _, vs in groups for v in vs if v is not None]
        extra = f'{indent}case {max(known) + 1}:\n{indent}    break;\n' if known and all(
            v is not None for _, _, vs in groups for v in vs) else None
        original = tuple(range(len(groups)))
        orders = [o for o in itertools.permutations(original) if o != original]
        has_local_label = any(m[1] != 'default' for m in _NAMED_LABEL.finditer(clean, groups[0][0], groups[-1][1]))
        candidates = []
        for order in (orders + [original] if has_local_label else [original] + orders):
            arms = [texts[k] for k in order]
            if order != original:
                candidates.append(arms)
            if extra:
                candidates.append(arms + [extra])
        start = source.rfind('\n', 0, groups[0][0]) + 1
        stop = source.rfind('\n', 0, body_close - 1) + 1  # the closing brace's line
        for arms in candidates[:LIMIT]:
            text = source[:start] + ''.join(arms) + source[stop:]
            if text == source:
                continue
            if has_local_label:
                labelled.append((len(groups), len(arms) > len(groups), text))
            elif text not in [t for _, t in result]:
                result.append((FAMILY, text))
    # Prefer a smaller arm reorder before adding a case or trying a larger switch.
    labelled.sort(key=lambda entry: entry[:2])
    local_choices = dict.fromkeys(text for _, _, text in labelled)
    return [(LOCAL_LABEL_FAMILY, text) for text in list(local_choices)[:LIMIT]] + result
