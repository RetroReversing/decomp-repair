"""m2c's two nested loops with an early exit, written as a `do`/`while` inside the outer loop with `return`s.

A search over pairs that returns as soon as one pair hits comes out of m2c as one `goto` ladder: the exhausted inner
loop jumps into the `else` of the guard around it, where the outer step is, and the hit `break`s out of both loops
to the one `return` through a result variable:

    for (;;) {
        r = 0;
        if (i < n) {
            j = 0;
            if (m != 0) {
                for (;;) {
                    r = 1;
                    if (f(i, j) == 0) { r = 1; if (g(j, i) == 0) { j += 1; if (j >= m) { goto next; } continue; } }
                    break;
                }
            } else {
    next:
                i += 1; continue;
            }
        }
        break;
    }
    return r;

The program it came from is `if (m != 0) { do { if (f(i, j) != 0 || g(j, i) != 0) return 1; j += 1; } while (j < m); }
i += 1;` inside the outer loop, and `return 0` after it. On an 84-instruction pairwise collision test (SN GCC 2.8.1,
N64) the `||` with the literal returns was the difference between 865 and 1641 with the same pointer temporaries: the
result variable takes a register the target does not have, and the `||` puts the `li` in both branches' delay slots.

nested_exit_loop_ladder
    The outer `for (;;)` ends `if (C) { .. if (G) { .. for (;;) { H if (a) { .. { step if (K) goto L; continue; } }
    break; } } else { L: S continue; } } break;` and only a `return` follows it. Written with the inner loop as
    `do { .. } while (!K);`, `S` falling through and each hit leaving through `return`. When the returned variable
    only ever takes literals, they are returned and it goes: one child with the hit tests joined by `||`, one with
    one `if` each. Otherwise the variable is returned. The judge decides each child.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'nested_exit_loop_ladder'
FAMILIES = (FAMILY,)
_FOREVER = re.compile(r'\b(?:for\s*\(\s*;\s*;\s*\)|while\s*\(\s*1\s*\))\s*\{')
_IF = re.compile(r'\bif\s*\(')
_FLOW = re.compile(r'\b(?:break|continue|goto|return|switch|case)\b')


def _statements(clean, start, end):
    """[(start, if_or_None)] of the `if`s at the top level of clean[start:end]: (at, condition span, block span,
    else block span or None). Unbraced `if`s are not listed."""
    found, depth, at = [], 0, start
    while at < end:
        char = clean[at]
        if char in '{(':
            depth += 1
        elif char in '})':
            depth -= 1
        elif depth == 0 and char == 'i':
            hit = _IF.match(clean, at, end)
            if hit and not re.search(r'\belse\s*$', clean[start:at]):
                parsed = _if(clean, hit, end)
                if parsed:
                    found.append(parsed)
                    at = parsed[3] if parsed[4] is None else parsed[4][1] + 1
                    continue
        at += 1
    return found


def _if(clean, hit, end):
    """(at, (condition start, end), (block inner start, end), after block, else inner span or None)."""
    paren = hit.end() - 1
    after = close(clean, paren, '(', ')')
    if not after:
        return None
    opening = re.compile(r'\s*\{').match(clean, after, end)
    if not opening:
        return None
    brace = opening.end() - 1
    done = close(clean, brace, '{', '}')
    if not done or done > end:
        return None
    other, span = re.compile(r'\s*else\s*\{').match(clean, done, end), None
    if other:
        stop = close(clean, other.end() - 1, '{', '}')
        if not stop:
            return None
        span = (other.end(), stop - 1)
    elif re.compile(r'\s*else\b').match(clean, done, end):
        return None
    return hit.start(), (paren + 1, after - 1), (brace + 1, done - 1), done, span


def _negate(condition):
    condition = condition.strip()
    flat = condition
    while re.search(r'\([^()]*\)', flat):
        flat = re.sub(r'\([^()]*\)', '_', flat)
    found = re.findall(r'<<|>>|->|&&|\|\||==|!=|<=|>=|<|>|\?', flat)
    compares = [op for op in found if op not in ('<<', '>>', '->')]
    if len(compares) == 1 and compares[0] in ('==', '!=', '<', '>=', '>', '<='):
        op = compares[0]
        flipped = {'==': '!=', '!=': '==', '<': '>=', '>=': '<', '>': '<=', '<=': '>'}[op]
        depth = 0
        for i, char in enumerate(condition):
            depth += (char == '(') - (char == ')')
            if depth == 0 and condition.startswith(op, i) and condition[i - 1] not in '<>-=!' \
                    and condition[i + len(op):i + len(op) + 1] not in ('<', '>', '='):
                return f'{condition[:i]}{flipped}{condition[i + len(op):]}'
    return f'!({condition})'


def _body(clean, opening, end):
    """The parts of one ladder whose outer loop opens at `opening`, or None."""
    done = close(clean, opening, '{', '}')
    if not done:
        return None
    tail = re.compile(r'\s*return\b\s*([^;]*);\s*\}').match(clean, done, end)
    if not tail or clean[tail.end():end].strip():
        return None
    ifs = _statements(clean, opening + 1, done - 1)
    if not ifs or ifs[-1][4] is not None or not re.fullmatch(r'\s*break\s*;\s*', clean[ifs[-1][3]:done - 1]):
        return None
    at, condition, block, _, _ = ifs[-1]
    inner_ifs = _statements(clean, *block)
    if not inner_ifs or inner_ifs[-1][4] is None:
        return None
    guard_at, guard, then, _, other = inner_ifs[-1]
    if clean[other[1] + 1:block[1]].strip():
        return None
    skip = re.fullmatch(rf'\s*({IDENT})\s*:(?P<step>[^{{}}:?]*?)\bcontinue\s*;\s*', clean[other[0]:other[1]])
    if not skip or _FLOW.search(skip['step']):
        return None
    loops = [m for m in _FOREVER.finditer(clean, then[0], then[1])]
    if not loops:
        return None
    loop = loops[0]
    stop = close(clean, loop.end() - 1, '{', '}')
    if not stop or clean[stop:then[1]].strip():
        return None
    label = skip[1]
    if len(re.findall(rf'\bgoto\s+{label}\s*;', clean[opening:done])) != 1 \
            or len(re.findall(rf'\bgoto\s+{label}\s*;', clean)) != 1:
        return None
    # the nest: `H if (a) { H2 if (b) { STEP if (K) { goto L; } continue; } } break;`
    start, finish = loop.end(), stop - 1
    levels, last = [], re.compile(r'\s*break\s*;\s*')
    ended = re.compile(rf'if\s*\((?P<k>(?:[^;{{}}])*?)\)\s*(?:\{{\s*goto\s+{label}\s*;\s*\}}|goto\s+{label}\s*;)'
                       r'\s*continue\s*;\s*$')
    while True:
        leaf = ended.search(clean, start, finish)
        if leaf and levels:
            step = (start, leaf.start())
            break
        found = _statements(clean, start, finish)
        if not found or found[-1][4] is not None or not last.fullmatch(clean, found[-1][3], finish):
            return None
        _, test, inside, _, _ = found[-1]
        levels.append(((start, found[-1][0]), test))
        start, finish, last = inside[0], inside[1], re.compile(r'\s*')
    straight = [(then[0], loop.start()), step] + [head for head, _ in levels]
    if any(_FLOW.search(clean, a, b) for a, b in straight):
        return None
    return {'outer': (opening + 1, done - 1), 'done': done, 'if': at, 'condition': condition, 'block': block,
            'guard_at': guard_at, 'guard': guard, 'then': then, 'skip': (other[0] + skip.start('step'),
            other[0] + skip.end('step')), 'loop': loop.start(), 'levels': levels, 'step': step,
            'exit': leaf.span('k'), 'result': (tail.start(1), tail.end(1)), 'tail': tail.end()}


def _literals(clean, source, part, name):
    """Whether `name` is a local that only takes literals and is only read by the final `return`."""
    if not re.fullmatch(IDENT, name):
        return None
    body = clean[part.opening:part.end]
    declared = re.findall(rf'(?m)^[ \t]*(?:unsigned\s+|signed\s+|register\s+)?(?!return\b){IDENT}\s+\**{name}\s*;[ \t]*\n?', body)
    assigned = re.findall(rf'(?<![\w.>&]){name}\s*=\s*-?{NUMBER}\s*;', body)
    uses = re.findall(rf'(?<![\w.>]){name}\b', body)
    return len(declared) == 1 and len(uses) == len(assigned) + 2


def _indent(body, depth):
    lines = []
    for line in (l.strip() for l in body.splitlines()):
        if not line:
            continue
        depth -= line.startswith('}')
        lines.append(line if re.fullmatch(rf'{IDENT}\s*:', line) else '    ' * depth + line)
        depth += line.count('{') - line.count('}') + line.startswith('}')
    return '\n'.join(lines)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    for hit in _FOREVER.finditer(clean, part.opening, part.end):
        found = _body(clean, hit.end() - 1, part.end)
        if found:
            break
    else:
        return []

    def text(a, b):
        return source[a:b].strip('\n').rstrip()

    result = text(*found['result']).strip()
    nest = [(text(*head), source[a:b].strip()) for head, (a, b) in found['levels']]
    heads = [head for head, _ in nest]
    results = []
    value = result
    zero = result
    drop = None
    if _literals(clean, source, part, result):
        assigned = re.compile(rf'(?<![\w.>&]){result}\s*=\s*(-?{NUMBER})\s*;')
        hits = [m for head, _ in found['levels'] for m in assigned.finditer(clean, *head)]
        before = list(assigned.finditer(clean, found['outer'][0], found['if']))
        if hits and before and len({m[1] for m in hits}) == 1:
            value, zero, drop = hits[-1][1], before[-1][1], result

    def strip(block):
        if drop is None:
            return block
        block = re.sub(rf'(?m)^[ \t]*{drop}\s*=\s*-?{NUMBER}\s*;[ \t]*\n?', '', block + '\n')
        return re.sub(rf'(?<![\w.>&]){drop}\s*=\s*-?{NUMBER}\s*;[ \t]*', '', block).rstrip()

    tests = [_negate(test) for _, test in nest]
    again = _negate(source[found['exit'][0]:found['exit'][1]])
    shapes = []
    if len(tests) > 1 and not any(strip(head).strip() for head in heads[1:]):
        joined = ' || '.join(t if re.fullmatch(rf'(?:{IDENT}\(.*\)|\(.*\))\s*[!=]=\s*\w+|{IDENT}', t) else f'({t})'
                             for t in tests)
        shapes.append([(heads[0], joined)])
    shapes.append(list(zip(heads, tests)))
    for shape in shapes:
        inner = []
        for head, test in shape:
            if strip(head).strip():
                inner.append(strip(head))
            inner.append(f'if ({test}) {{\nreturn {value};\n}}')
        inner.append(strip(text(*found['step'])))
        lead = strip(text(found['then'][0], found['loop']))
        pieces = [
            strip(text(found['outer'][0], found['if'])),
            f'if ({text(*found["condition"])}) {{',
            strip(text(found['block'][0], found['guard_at'])),
            f'if ({text(*found["guard"])}) {{',
            lead,
            'do {', *inner, f'}} while ({again});',
            '}',
            strip(text(*found['skip'])),
            'continue;',
            '}',
            'break;',
        ]
        pad = len(source[:hit.start()].rsplit('\n', 1)[-1])
        body = _indent('\n'.join(p for p in pieces if p.strip()), pad // 4 + 1)
        edits = [(found['outer'][0], found['outer'][1], f'\n{body}\n{" " * pad}'),
                 (found['done'], found['tail'] - 1, f'\n    return {zero};\n')]
        if drop:
            declared = re.compile(rf'(?m)^[ \t]*(?:unsigned\s+|signed\s+|register\s+)?(?!return\b){IDENT}\s+\**{drop}\s*;[ \t]*\n')
            m = declared.search(clean, part.opening, hit.start())
            if m:
                edits.append((m.start(), m.end(), ''))
            # the statements before the outer loop that set the dropped variable
            for m in re.finditer(rf'(?m)^[ \t]*{drop}\s*=\s*-?{NUMBER}\s*;[ \t]*\n', clean[:hit.start()]):
                if m.start() > part.opening:
                    edits.append((m.start(), m.end(), ''))
        child = edit(source, edits)
        if child != source and child not in [c for _, c in results]:
            results.append((FAMILY, child))
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
