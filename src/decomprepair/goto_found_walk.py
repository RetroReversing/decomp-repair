"""m2c's list search whose found node is handled in the other arm of the first test, written as the walk it was.

A loop that follows a link until a node matches, then works on that node (it does not return it), comes back from m2c
with the match test outside the loop and the work as the other arm:

    if (KEY(p) != 3) {
    loop_58:
        p = NEXT(p);
        if (p != NULL) {
            if (KEY(p) == 3) {
                goto block_60;
            }
            goto loop_58;
        }
    } else {
    block_60:
        WORK(p);
    }

GCC lays that out differently from the original loop. As the program it is:

    while (KEY(p) != 3) {
        p = NEXT(p);
        if (p == NULL) {
            goto block_60_done;
        }
    }
    WORK(p);
    block_60_done:;

In a `void` function where nothing runs after the `if`/`else`, leaving the walk is `return;`, offered first: no label
is left for the other rewrites of a draft's gotos to decline on.

Measured on a 259-instruction N64 object reset (SN, `-G0 -mips3 -O2`): from its draft the step is worth 560 points
alone (4400 -> 3840 after the join before it), and it is one of the steps of the exact match.

`goto_search_loop` (search_loop_repairs) is the other shape, where the loop returns the node. Offered when the two
tests are the same comparison negated, the loop's step is plain assignments, and the labels have no other jumps.
`goto_found_walk`. A candidate; the exact judge decides."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'goto_found_walk'
FAMILIES = (FAMILY,)
LIMIT = 4
_IF = re.compile(r'(?<![\w])if\s*\(')
_OPPOSITE = {'==': '!=', '!=': '=='}
_NIL = r'(?:NULL|0)'


def _arm(clean, brace):
    """(inside start, inside end, end) of the braced block opening at `brace`, or None."""
    if not clean.startswith('{', brace):
        return None
    end = close(clean, brace, '{', '}')
    return None if end is None else (brace + 1, end - 1, end)


def _skip(clean, index):
    return len(clean) - len(clean[index:].lstrip())


def _if_at(clean, match):
    """(condition span, block) of the braced `if` that `match` opens, or None."""
    after = close(clean, match.end() - 1)
    if after is None:
        return None
    block = _arm(clean, _skip(clean, after))
    return None if block is None else ((match.end(), after - 1), block)


def _squash(text):
    return re.sub(r'\s+', '', text)


def _negated(first, second):
    """Whether two comparisons are the same operands with `==` and `!=` exchanged."""
    left, right = _squash(first), _squash(second)
    marks = list(re.finditer(r'==|!=', left))
    if len(marks) != 1:
        return False
    mark = marks[0]
    return right == left[:mark.start()] + _OPPOSITE[mark[0]] + left[mark.end():]


def _ends_function(clean, index):
    """Whether only closing braces and skipped `else` arms lead from `index` to the function's end, in no loop."""
    while True:
        index = _skip(clean, index)
        if index >= len(clean):
            return True
        if clean[index] == '}':
            index += 1
            continue
        other = re.compile(r'else\b\s*(?:if\b\s*)?').match(clean, index)
        if not other:
            return False
        index = other.end()
        if clean.startswith('(', index):
            index = close(clean, index)
            if index is None:
                return False
            index = _skip(clean, index)
        arm = _arm(clean, index)
        if arm is None:
            return False
        index = arm[2]


def _rewrite(body, clean, match):
    outer = _if_at(clean, match)
    if outer is None:
        return None
    (c0, c1), (a, b, end) = outer
    other = re.compile(r'\s*else\s*').match(clean, end)
    if not other:
        return None
    found = _arm(clean, other.end())
    if found is None:
        return None
    f0, f1, finish = found
    found_label = re.match(r'\s*([A-Za-z_]\w*)\s*:(?!:)', clean[f0:f1])
    loop_label = re.match(r'\s*([A-Za-z_]\w*)\s*:(?!:)', clean[a:b])
    if not found_label or not loop_label:
        return None
    found_name, loop_name = found_label[1], loop_label[1]
    start = a + loop_label.end()
    guard = _IF.search(clean, start, b)
    if guard is None:
        return None
    step = body[start:guard.start()].strip()
    if not step or not re.fullmatch(r'(?:\s*[A-Za-z_]\w*\s*=(?!=)[^;{}]*;)+\s*', _blank(step)):
        return None
    walker = re.findall(r'([A-Za-z_]\w*)\s*=(?!=)', _blank(step))[-1]
    inner = _if_at(clean, guard)
    if inner is None or clean[inner[1][2]:b].strip():
        return None
    (g0, g1), (i0, i1, _) = inner
    if not re.fullmatch(rf'\s*{walker}\s*!=\s*{_NIL}\s*', clean[g0:g1]):
        return None
    test = _IF.search(clean, i0, i1)
    if test is None or clean[i0:test.start()].strip():
        return None
    last = _if_at(clean, test)
    if last is None:
        return None
    (t0, t1), (j0, j1, jump_end) = last
    if (not re.fullmatch(rf'\s*goto\s+{found_name}\s*;\s*', clean[j0:j1])
            or not re.fullmatch(rf'\s*goto\s+{loop_name}\s*;\s*', clean[jump_end:i1])
            or not _negated(body[c0:c1], body[t0:t1])):
        return None
    for label in (found_name, loop_name):
        if len(re.findall(rf'\bgoto\s+{label}\b', clean)) != 1:
            return None
    work = body[f0 + found_label.end():f1]
    if re.search(r'(?<![?\w])\b[A-Za-z_]\w*\s*:(?!:)|\b(?:case|default)\b', _blank(work)):
        return None
    indent = body[body.rfind('\n', 0, match.start()) + 1:match.start()]
    if indent.strip():
        indent = ''
    done = f'{found_name}_done'
    if re.search(rf'\b{done}\b', clean):
        return None
    leaves = [f'goto {done};']
    returns = (re.match(r'[^{;]*\bvoid\s+(?!\*)', clean) and not re.search(r'\b(?:for|while|do|switch)\b', clean[:match.start()])
               and _ends_function(clean, finish))
    if returns:
        leaves.insert(0, 'return;')
    pad = indent + '    '
    texts = []
    for leave in leaves:
        lines = [f'while ({body[c0:c1].strip()}) {{', *(pad + line.strip() for line in step.splitlines()),
                 f'{pad}if ({walker} == NULL) {{', f'{pad}    {leave}', f'{pad}}}', f'{indent}}}']
        lines += [indent + line.strip() for line in work.strip().splitlines()]
        if leave.startswith('goto'):
            lines.append(f'{indent}{done}:;')
        texts.append(body[:match.start()] + '\n'.join(lines) + body[finish:])
    return texts


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    head, body, tail = source[:span[0]], source[span[0]:span[1]], source[span[1]:]
    if 'goto' not in body:
        return []
    clean = _blank(body)
    results = []
    for match in _IF.finditer(clean):
        results += [(FAMILY, head + text + tail) for text in _rewrite(body, clean, match) or []]
        if len(results) >= LIMIT:
            break
    return results[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
