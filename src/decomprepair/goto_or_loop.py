"""m2c's `while (a || b)` loop, written back from the `goto` into its `else`.

m2c draws a loop whose condition is an `||` as a labelled `if` that jumps from one arm into the middle of the other:

    loop:
        if (x <= 0x10000) {
            if (y > 0x10000) {
                x >>= 1;
                goto step;
            }
            return f(x, y);
        } else {
            x >>= 1;
    step:
            y >>= 1;
            goto loop;
        }

The body runs when `!(x <= 0x10000) || (y > 0x10000)`, so this is `while (x > 0x10000 || y > 0x10000) { x >>= 1;
y >>= 1; }` followed by the `return`. `goto_structure_repairs` and `nested_goto_loop` only wrap it in `for (;;)` and
keep the inner `goto`. On a 39-instruction N64 vector length (SN64 GCC 2.8.1, `-G0 -mips3 -mgp32 -mfp32 -O2`) the draft's
form was 670 in the app's judge; this child is what brought it within the last few register rows.

Only when both labels have no other `goto`, the two copies of the first arm's statements are the same, and the
statements moved into the loop hold no `break`, `continue`, `case`, label or other `goto`. A candidate rewrite.
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'goto_or_loop'
FAMILIES = (FAMILY,)

_HEAD = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<loop>[A-Za-z_]\w*)\s*:\s*if\s*(?=\()')
_NEGATED = {'<=': '>', '>': '<=', '<': '>=', '>=': '<', '==': '!=', '!=': '=='}
_MOVED = re.compile(r'\b(?:break|continue|case|default|goto)\b|\b[A-Za-z_]\w*\s*:(?!:)')


def _block(clean, at):
    """(inside start, inside end, position past the brace) of the block opening at or after the space at `at`."""
    opening = re.compile(r'\s*\{').match(clean, at)
    if not opening:
        return None
    end = close(clean, opening.end() - 1, '{', '}')
    return None if end is None else (opening.end(), end - 1, end)


def _negate(condition):
    comparison = re.fullmatch(r'\s*([A-Za-z_]\w*)\s*(<=|>=|==|!=|<|>)\s*(-?\w+)\s*', condition)
    if comparison:
        return f'{comparison[1]} {_NEGATED[comparison[2]]} {comparison[3]}'
    return f'!({condition.strip()})'


def _words(text):
    return re.sub(r'\s+', '', text)


def _rewrite(part, head):
    source, clean = part.source, part.clean
    shut = close(clean, head.end())
    if shut is None:
        return None
    condition = source[head.end() + 1:shut - 1]
    then = _block(clean, shut)
    if not then:
        return None
    inner = re.compile(r'\s*if\s*(?=\()').match(clean, then[0])
    if not inner:
        return None
    inner_shut = close(clean, inner.end())
    second = source[inner.end() + 1:inner_shut - 1] if inner_shut else None
    arm = _block(clean, inner_shut) if inner_shut else None
    other = re.compile(r'\s*else\b').match(clean, then[2])
    other = _block(clean, other.end()) if other else None
    if not arm or not other:
        return None
    jump = re.search(r'\bgoto\s+(?P<label>[A-Za-z_]\w*)\s*;\s*$', clean[arm[0]:arm[1]])
    if not jump:
        return None
    step, loop = jump['label'], head['loop']
    mark = re.search(rf'(?m)^[ \t]*{step}\s*:', clean[other[0]:other[1]])
    again = re.search(rf'\bgoto\s+{loop}\s*;\s*$', clean[other[0]:other[1]])
    if (not mark or not again or len(re.findall(rf'\bgoto\s+{step}\b', part.body)) != 1
            or len(re.findall(rf'\bgoto\s+{loop}\b', part.body)) != 1):
        return None
    first = (arm[0], arm[0] + jump.start())
    copy = (other[0], other[0] + mark.start())
    rest = (other[0] + mark.end(), other[0] + again.start())
    if (_words(clean[first[0]:first[1]]) != _words(clean[copy[0]:copy[1]])
            or _MOVED.search(clean[copy[0]:copy[1]]) or _MOVED.search(clean[rest[0]:rest[1]])):
        return None
    leave = (arm[2], then[1])
    if re.search(r'(?m)^\s*(?!default\b)[A-Za-z_]\w*\s*:(?!:)', clean[leave[0]:leave[1]]):
        return None
    brace = other[2] - 1
    indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, brace) + 1:brace])[0]

    def lines(spans, margin):
        kept = [line.strip() for start, end in spans for line in source[start:end].split('\n') if line.strip()]
        return ''.join(f'{margin}{line}\n' for line in kept)

    wanted = second.strip()
    if not re.fullmatch(r'[A-Za-z_]\w*\s*(?:<=|>=|==|!=|<|>)\s*-?\w+', wanted):
        wanted = f'({wanted})'
    text = (f'{indent}while ({_negate(condition)} || {wanted}) {{\n'
            + lines((copy, rest), indent + '    ') + f'{indent}}}\n' + lines((leave,), indent).rstrip('\n'))
    return edit(source, [(head.start(), other[2], text)])


def variants(source, name):
    part = view(source, name)
    if not part or 'goto' not in part.body:
        return []
    out = []
    for head in _HEAD.finditer(part.clean, part.opening + 1, part.end - 1):
        rewritten = _rewrite(part, head)
        if rewritten:
            out.append((FAMILY, rewritten))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
