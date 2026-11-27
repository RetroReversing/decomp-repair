"""The statements after a switch that ends a `void` function, written in each arm that breaks to them, and the arms
reordered.

m2c writes the code two arms share once, after the switch. The game's source had it in the arms, which the compiler
merged where the last of them sits, so a later arm follows the merged copy:

    switch (v) {                        switch (v) {
    case 1: a(); break;                 case 1: a(); n++; break;
    case 2: b(); return;        ->      case 3: c(); n++; break;
    case 3: c(); break;                 case 2: b(); return;
    default: return;                    default: return;
    }                                   }
    n++;                            }
    }

Neither half is enough alone: on a 142-instruction N64 state routine (KMC GCC 2.7.2, `-O1`) the copied tail scored 1240
and the arm order 920 where the two together were exact. `switch_case_order` declines it too: with m2c's `default:
return;` the switch has five arms. So the copied tail is offered alone and with the other arms in each order, the
`default:` arm kept where it is, last. Only a switch with a `default:` arm, whose every `break` ends an arm.
"""
import itertools
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'switch_tail_arm_order'
FAMILIES = (FAMILY,)
MAX_ARMS = 4  # arms besides `default:`: 23 other orders
MAX_TAIL = 4
_LABEL = re.compile(r'(?:case\b[^:;{}]*|default\s*):')
_END = re.compile(r'(?:\bbreak|\breturn)\s*;\s*$')


def _labels(body, start, end):
    """The labels of the switch whose braces hold body[start:end], not those of a nested block."""
    found, depth, at = [], 0, start
    for label in _LABEL.finditer(body, start, end):
        depth += body.count('{', at, label.start()) - body.count('}', at, label.start())
        at = label.start()
        if not depth:
            found.append(label)
    return found


def variants(source, name):
    span = find(source, name)
    if not span or not re.search(r'\bvoid\s+' + re.escape(name) + r'\s*\(', source):
        return []
    body = _blank(source)
    opening = body.find('{', span[0], span[1])
    end = close(body, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    switches = list(re.finditer(r'\bswitch\s*\(', body[opening:end]))
    if not switches:
        return []
    paren = opening + switches[0].end() - 1
    after = close(body, paren)
    first = body.find('{', after) if after else -1
    last = close(body, first, '{', '}') if first >= 0 else None
    if not last:
        return []
    tail = body[last:end - 1]
    if (not tail.strip() or not tail.rstrip().endswith(';') or tail.count(';') > MAX_TAIL or re.search(
            r'[{}:?#]|\b(?:if|for|while|do|goto|switch|return|break|continue|case|else)\b', tail)):
        return []
    lines = [line.strip() for line in source[last:end - 1].split('\n') if line.strip()]
    labels = _labels(body, first + 1, last - 1)
    if not labels or labels[0].start() != first + 1 + len(body[first + 1:last - 1]) - len(body[first + 1:last - 1].lstrip()):
        return []
    starts = [source.rfind('\n', 0, label.start()) + 1 for label in labels]
    stop = source.rfind('\n', 0, last - 1) + 1
    arms, group = [], None
    for k, label in enumerate(labels):
        group = starts[k] if group is None else group
        until = starts[k + 1] if k + 1 < len(labels) else stop
        text = body[label.end():until]
        if not text.strip():
            continue
        is_default = any(body[hit.start():].startswith('default') for hit in labels if group <= hit.start() < until)
        arms.append([group, until, is_default])
        group = None
    if group is not None or not any(arm[2] for arm in arms) or not _END.search(body[arms[-1][0]:arms[-1][1]]):
        return []
    texts, breaks, closed = [], 0, True
    for start, until, _ in arms:
        clean, text = body[start:until], source[start:until]
        ending = re.search(r'\bbreak\s*;\s*$', clean)
        if ending:
            line = text.rfind('\n', 0, ending.start()) + 1
            if text[line:ending.start()].strip():
                return []
            indent = text[line:ending.start()]
            text = text[:line] + ''.join(indent + each + '\n' for each in lines) + text[line:]
            breaks += 1
        closed = closed and bool(_END.search(clean))
        texts.append(text)
    # a `break` that does not end an arm would still skip to where the tail was
    if breaks < 1 or len(re.findall(r'\bbreak\s*;', body[first:last])) != breaks:
        return []
    head, rest = source[:starts[0]], source[stop:last] + '\n' + source[end - 1:]
    out = [(FAMILY, head + ''.join(texts) + rest)]
    movable = [k for k, arm in enumerate(arms) if not arm[2]]
    if closed and 1 < len(movable) <= MAX_ARMS and arms[-1][2]:
        for order in itertools.permutations(movable):
            if list(order) != movable:
                out.append((FAMILY, head + ''.join(texts[k] for k in order) + texts[-1] + rest))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
