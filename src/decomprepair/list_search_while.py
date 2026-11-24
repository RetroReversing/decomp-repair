"""m2c's `goto` list walk that stops at a match, written as the `while` loop with a `break` it came from.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) projectile update of 2,503 instructions, which unlinks an
object from a singly linked list. m2c writes the walk as

    p = head;
    if (p != NULL) {
    loop_95:
        next = p->link;
        if (next != target) {
            p = next;
            if (p != NULL) {
                goto loop_95;
            }
        } else {
            p->link = next->link;
        }
    }

The target compares every node with `target` held in a register loaded once before the walk, and its unlink block sits
out of line; from the `goto` form the compiler reloaded the global `target` on each step (no loop notes, so loop.c
never hoisted it), and the `for (;;)`/`continue` spellings `goto_backward_loop` and `nested_goto_loop` offer compile
to the same code. As `while (p != NULL) { next = p->link; if (next == target) { ...; break; } p = next; }` the
function went 11416 -> 10131.

list_search_while
    The shape above (any names, any link expression, any match body) becomes the `while`. One child per walk, then
    one with every walk. Hypothesis from the match, not confirmed in the compiler source: the `while` gives loop.c a
    loop to hoist the compared global out of. The exact judge decides.
"""
import re

FAMILY = 'list_search_while'
FAMILIES = (FAMILY,)
LIMIT = 8

_ID = r'[A-Za-z_]\w*'
_HEAD = re.compile(
    rf'(?m)^(?P<i0>[ \t]*)if \((?P<p>{_ID}) != NULL\) \{{\n'
    rf'(?P<label>{_ID}):\n'
    rf'(?P<i1>[ \t]*)(?P<n>{_ID}) = (?P<link>[^;\n]+);\n'
    rf'[ \t]*if \((?P=n) != (?P<x>[^\n]+)\) \{{\n'
    rf'[ \t]*(?P=p) = (?P=n);\n'
    rf'[ \t]*if \((?P=p) != NULL\) \{{\n'
    rf'[ \t]*goto (?P=label);\n'
    rf'[ \t]*\}}\n'
    rf'[ \t]*\}} else \{{\n')


def _block_end(source, start):
    """Index just past the line closing the block whose body starts at `start` (depth one), or -1."""
    depth = 1
    for found in re.finditer(r'[{}]', source[start:]):
        depth += 1 if found.group() == '{' else -1
        if depth == 0:
            close = start + found.start()
            line_end = source.find('\n', close)
            return close, (len(source) if line_end < 0 else line_end + 1)
    return -1, -1


def _walks(source):
    walks = []
    for head in _HEAD.finditer(source):
        else_close, else_end = _block_end(source, head.end())
        if else_close < 0:
            continue
        outer_close, outer_end = _block_end(source, else_end)
        if outer_close < 0 or source[else_end:outer_close].strip():
            continue
        body = source[head.end():source.rfind('\n', 0, else_close) + 1]
        if re.search(r'\b(?:break|continue)\b', body) or re.search(rf'\b{re.escape(head.group("label"))}\b', body):
            continue
        if re.search(rf'\b{re.escape(head.group("label"))}\b', source[:head.start()] + source[outer_end:]):
            continue
        walks.append((head, body, outer_end))
    return walks


def _rewrite(source, walk):
    head, body, end = walk
    i0, p, n = head.group('i0'), head.group('p'), head.group('n')
    step = i0 + '    '
    lines = [line for line in body.split('\n') if line.strip()]
    margin = min(len(line) - len(line.lstrip()) for line in lines) if lines else 0
    inner = ''.join(f'{step}    {line[margin:]}\n' for line in lines)
    text = (f'{i0}while ({p} != NULL) {{\n'
            f'{step}{n} = {head.group("link")};\n'
            f'{step}if ({n} == {head.group("x")}) {{\n'
            f'{inner}'
            f'{step}    break;\n'
            f'{step}}}\n'
            f'{step}{p} = {n};\n'
            f'{i0}}}\n')
    return source[:head.start()] + text + source[end:]


def variants(source, name):
    walks = _walks(source)
    result = []
    for walk in walks:
        result.append((FAMILY, _rewrite(source, walk)))
    if len(walks) > 1:
        text = source
        for walk in reversed(walks):
            text = _rewrite(text, walk)
        result.append((FAMILY, text))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
