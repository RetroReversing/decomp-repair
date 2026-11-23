"""The statement both arms of an if/else end with, written once after the test.

    if (!(flags & 8)) { word[2] = 1; mode = 0; } else { mode = 0; }        if (!(flags & 8)) { word[2] = 1; } mode = 0;

m2c writes the join of a state machine's arms into each arm (and `goto` target), so an arm that sets a value on the
way and one that only sets it come out as two full copies. The game wrote the common statement once. GCC 2.7.2's
cross-jumping merges the tails after register allocation either way, but only when the label it has to merge at was
there before the pass: the two spellings differ in which branch becomes the conditional's skip, so the `beql` over the
single store is laid out one way for the hoisted form and the other way for the copies (the jump table's second and
third arms of a 417-instruction input handler: two `beql` targets, the last 20 of a function matched otherwise).

Offered for `if (C) { ...; T; } else { T; }` with braced arms and identical last statements (spacing ignored), where the
then arm has more than the tail: one child per if. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'common_arm_tail_hoist'
FAMILIES = (FAMILY,)
_IF = re.compile(r'\bif\s*\(')


def _last(block):
    """(start, end) of the last statement of a block body `{ ... }` given without its braces, when it is one simple
    statement; else None."""
    stripped = block.rstrip()
    if not stripped.endswith(';'):
        return None
    start = max(stripped.rfind(';', 0, -1), stripped.rfind('{'), stripped.rfind('}')) + 1
    statement = stripped[start:].strip()
    if not statement or re.search(r'[{}]|\b(?:if|else|for|while|do|switch|case|default|return|break|continue|goto)\b', statement):
        return None
    return start + (len(stripped[start:]) - len(stripped[start:].lstrip())), len(stripped)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for hit in _IF.finditer(clean, part.opening + 1, part.end):
        shut = close(clean, hit.end() - 1)
        then = re.compile(r'\s*\{').match(clean, shut) if shut else None
        if not then:
            continue
        then_end = close(clean, then.end() - 1, '{', '}')
        other = re.compile(r'\s*else\s*\{').match(clean, then_end) if then_end else None
        if not other:
            continue
        else_end = close(clean, other.end() - 1, '{', '}')
        if not else_end:
            continue
        then_body = clean[then.end():then_end - 1]
        else_body = clean[other.end():else_end - 1]
        a, b = _last(then_body), _last(else_body)
        if not a or not b:
            continue
        tail = then_body[a[0]:a[1]]
        if re.sub(r'\s+', '', tail) != re.sub(r'\s+', '', else_body[b[0]:b[1]]) or not then_body[:a[0]].strip():
            continue
        if re.sub(r'\s+', '', else_body[:b[0]]):
            continue  # the else arm has more than the tail
        before = clean[:hit.start()].rstrip()
        if before[-1:] not in (';', '{', '}') and not re.search(r'\belse\Z', before):
            continue  # the `if` is the whole body of a test or loop: a statement after it would leave that body
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, hit.start()) + 1:])[0]
        kept = source[then.end():then.end() + a[0]].rstrip()
        text = f'{source[hit.start():then.end()]}{kept}\n{indent}}}\n{indent}{source[then.end() + a[0]:then.end() + a[1]].strip()}'
        if before.endswith('else'):  # `else if`: the else gets the braces its two statements need
            text = f'{{\n{indent}{text}\n{indent}}}'
        out.append((FAMILY, edit(source, [(hit.start(), else_end, text)])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
