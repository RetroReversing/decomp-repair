"""m2c's byte offset recomputed from a loop's counter, written as the `for` loop over that counter.

An indexed loop the compiler did not reduce to a pointer comes back with the scaled index in a variable of its own,
computed once before the loop and again after each step:

    off = 0 * 4;                              for (; i < 10; i++) {
    do {                                          if (*(s32 *)((i * 4) + table) < score) {
        if (*(s32 *)(off + table) < score) {  ->      ...
            ...                                   }
        }                                     }
        i += 1;
        off = i * 4;
    } while (i < 10U);

Offered when the offset is only set those two ways, the factors agree, the offset is only read between them, and the
counter was set to the same start earlier with nothing but the loop writing it since on a straight path (`i = 0;` before
the branch that leads here), so the loop's first test is true and the offset is `i * K` everywhere it is read. From an
N64 table insertion with one such loop per arm of an `if` (SN64 GCC 2.8.1). Children: every such loop at once, then each
alone. The exact judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'recomputed_offset_for_loop'
FAMILIES = (FAMILY,)
LIMIT = 4
_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_HEAD = re.compile(rf'(?P<offset>{_ID})\s*=\s*(?P<start>{_NUM})\s*\*\s*(?P<scale>{_NUM})\s*;\s*do\s*(?P<do>\{{)')


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
    offset, scale = hit['offset'], int(hit['scale'], 0)
    start = int(hit['start'], 0)
    do_end = close(clean, hit.start('do'), '{', '}')
    if not do_end:
        return None
    body_start, body_end = hit.end('do'), do_end - 1
    test = re.compile(rf'\s*while\s*\(\s*(?P<counter>{_ID})\s*<\s*(?P<limit>{_NUM})U?\s*\)\s*;').match(clean, do_end)
    if not test or start >= int(test['limit'], 0):
        return None
    counter = test['counter']
    tail = re.search(rf'\n[ \t]*(?:{counter}\s*\+=\s*1|{counter}\+\+|\+\+{counter})\s*;'
                     rf'[ \t]*\n[ \t]*{offset}\s*=\s*{counter}\s*\*\s*(?P<scale>{_NUM})\s*;[ \t]*(?=\n[ \t]*\Z)',
                     clean[body_start:body_end])
    if not tail or int(tail['scale'], 0) != scale:
        return None
    inside = clean[body_start:body_start + tail.start()]
    if re.search(rf'\b{offset}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--|&)\s*{offset}\b|\b{offset}\s*(?:\+\+|--)|'
                 rf'\bcontinue\b|\bgoto\b', inside):
        return None
    declaration = re.search(rf'(?<=[;{{}}])\n[ \t]*(?:s32|u32|int|unsigned int)\s+{offset}\s*;', clean[opening:end])
    if not declaration:
        return None
    declared = (opening + declaration.start(), opening + declaration.end())
    spans = [declared, (hit.start(), test.end())]
    if any(not any(a <= opening + use.start() < b for a, b in spans)
           for use in re.finditer(rf'\b{offset}\b', clean[opening:end])):
        return None
    if not _starts_at(clean, opening, hit.start(), counter, start):
        return None
    body = source[body_start:body_start + tail.start()]
    body = re.sub(rf'\b{offset}\b', f'({counter} * {scale})', body)
    indent = source[source.rfind('\n', 0, hit.start()) + 1:hit.start()]
    loop = f'for (; {counter} < {test["limit"]}; {counter}++) {{{body}\n{indent}}}'
    return [(declared[0], declared[1], ''), (hit.start(), test.end(), loop)]


def _starts_at(clean, opening, at, counter, start):
    """Whether the last write to `counter` that every path to `at` runs is `counter = start;`: a statement in a block
    that encloses `at`, with no write to it between the two that could run (a sibling arm's cannot)."""
    writes = re.finditer(rf'\b{counter}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{counter}\b|\b{counter}\s*(?:\+\+|--)',
                         clean[opening:at])
    enclosing = _blocks(clean, opening, at)
    for write in reversed(list(writes)):
        where = _blocks(clean, opening, opening + write.start())
        if where == enclosing[:len(where)]:
            return bool(re.compile(rf'{counter}\s*=\s*(?:0[xX]0*{start:x}|{start})\s*;').match(clean, opening + write.start()))
        if not _sibling(clean, opening + write.start(), at, where, enclosing):
            return False
    return False


def _blocks(clean, opening, at):
    """The positions of the braces open at `at`."""
    stack = []
    for brace in re.finditer(r'[{}]', clean[opening:at]):
        if brace[0] == '{':
            stack.append(opening + brace.start())
        elif stack:
            stack.pop()
    return stack


def _sibling(clean, write, at, where, enclosing):
    """Whether the write is inside the `if` arm whose `else` holds `at`."""
    shared = 0
    while shared < min(len(where), len(enclosing)) and where[shared] == enclosing[shared]:
        shared += 1
    if shared >= len(where) or shared >= len(enclosing):
        return False
    first = close(clean, where[shared], '{', '}')
    other = re.compile(r'\s*else\b\s*\{').match(clean, first) if first else None
    return bool(other) and other.end() - 1 == enclosing[shared]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 30}
