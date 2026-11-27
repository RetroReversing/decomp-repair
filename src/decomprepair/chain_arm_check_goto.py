"""chain_arm_check_goto: two arms of one `if` chain that end alike, one of them jumping into the other's ending.

    if (p == 0) { ...; if (ok) { goto done; } }         if (p == 0) { ...; check: if (ok) { goto done; } }
    else if (p == 1) { ...; }                    ->     else if (p == 1) { ...; }
    else if (p == 2) { ...; if (ok) { goto done; } }    else if (p == 2) { ...; goto check; }

Both arms go on to the same place, the end of the chain, so the program is the same. The compiler's cross-jumping would
merge the identical endings by itself, but it keeps the later copy and sends the earlier arm to it; when the target has
the later arm jumping back into the earlier one, the source says so with the `goto` (m2c writes `goto block_N;` for it
too). A 249-instruction N64 function with a result flag per arm (`sn-n64-281 -G0 -mips3 -O2`) went from 1300 to 90 with
this one edit. `identical_run_goto` takes only longer runs that a `break;` follows.

An ending is the arms' common last statements: one holding a `goto` or a `return`, or at least two. It holds no label,
`case` or declaration, and neither arm declares a name it uses. Children: the later arm jumping into the earlier one for
each pair, then the earlier into the later.
"""
import re

from .csource import _blank
from .goto_structure_repairs import IDENT, _labels, _paths, walk
from .one_goto_run_copy import body, declares

FAMILY = 'chain_arm_check_goto'
FAMILIES = (FAMILY,)
LIMIT = 8
MAX_ARMS = 12
MAX_ENDING = 6  # statements


def _chain(head):
    """The arm blocks of an `if` chain, in order."""
    arms, node = [], head
    while node is not None:
        arms.append(node.parts['then'])
        other, node = node.parts.get('other'), None
        if other:
            if len(other['stmts']) == 1 and other['stmts'][0].kind == 'if':
                node = other['stmts'][0]
            else:
                arms.append(other)
    return [arm for arm in arms if arm['block']][:MAX_ARMS]


def _chains(stmts):
    nested = set()
    for statement, _ in _paths(stmts):
        if statement.kind != 'if' or id(statement) in nested:
            continue
        node = statement
        while node.parts.get('other') and len(node.parts['other']['stmts']) == 1 \
                and node.parts['other']['stmts'][0].kind == 'if':
            node = node.parts['other']['stmts'][0]
            nested.add(id(node))
        yield _chain(statement)


def _text(clean, statement):
    return ' '.join(clean[statement.start:statement.end].split())


def _ending(clean, first, second):
    """How many last statements two arms share that may be jumped into (0: none worth it)."""
    left, right = first['stmts'], second['stmts']
    count = 0
    while count < min(len(left), len(right), MAX_ENDING):
        a, b = left[-1 - count], right[-1 - count]
        if _text(clean, a) != _text(clean, b) or _labels([a]) or _labels([b]):
            break
        if any(s.kind == 'case' or declares(clean, s) for s, _ in walk([a])):
            break
        count += 1
    if not count:
        return 0
    shared = left[-count:]
    jumps = any(s.kind == 'goto' or s.kind == 'simple' and re.match(r'return\b', clean[s.start:s.end])
                for s, _ in walk(shared))
    if count == 1 and not jumps:
        return 0
    names = set(re.findall(IDENT, clean[shared[0].start:shared[-1].end]))
    for arm in (first, second):
        for statement in arm['stmts']:
            if declares(clean, statement) and names.intersection(re.findall(IDENT, clean[statement.start:statement.end])):
                return 0
    return count


def _jump(source, kept, dropped, count, label):
    target, gone = kept['stmts'][-count], dropped['stmts'][-count:]
    edits = [(gone[0].start, gone[-1].end, f'goto {label};'), (target.start, target.start, f'{label}: ')]
    for start, end, replacement in sorted(edits, reverse=True):
        source = source[:start] + replacement + source[end:]
    return source


def variants(source, name):
    """[(family, source)]: one arm of a chain jumping into another arm's identical ending."""
    parsed = body(source, name)
    if not parsed:
        return []
    clean, stmts = parsed
    used = set(re.findall(IDENT, _blank(source)))
    label = next(f'check_{i}' for i in range(len(used) + 1) if f'check_{i}' not in used)
    pairs = []
    for arms in _chains(stmts):
        for i in range(len(arms)):
            for j in range(i + 1, len(arms)):
                count = _ending(clean, arms[i], arms[j])
                if count:
                    pairs.append((arms[i], arms[j], count))
    children = [_jump(source, first, second, count, label) for first, second, count in pairs]
    children += [_jump(source, second, first, count, label) for first, second, count in pairs]
    return [(FAMILY, text) for text in list(dict.fromkeys(children))[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
