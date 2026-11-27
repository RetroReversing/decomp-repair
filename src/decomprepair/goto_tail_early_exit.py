"""A guarded block whose first tests jump to the code after it, written as the early exit those tests were.

m2c writes a function that bails out with a store when either of two tests fails as

    if (distance(...) < 0x2001U) {
        if (ship->state == 0xFFFF) {
            goto block_3;
        }
        ...                             /* the work */
        return;
    }
    block_3:
    obj->dead = 1;

KMC and SN GCC lay that out with the work first and the shared exit after it. The game had the exit first,
`if (distance(...) >= 0x2001U || ship->state == 0xFFFF) { obj->dead = 1; return; }` with the work after it: the target
branches over the exit to the work (`bne` past a `j end; sb`) where the draft branched past the work to the exit
(`beq`). On a 67-instruction N64 function this edit took the saved best from 405 to 15 and, with the caller's leading
argument passed on (`leading_argument_widen`), to 0.

Variants, for a `if (A) { if (B) goto L; REST return; } L: TAIL` at the function's own level, `L` used only by those
guards (one or more of them, at the head of the block):

- one test: `if (!A || B) { TAIL return; } REST`
- the tests apart: `if (!A) { TAIL return; } if (B) { TAIL return; } REST`

`TAIL` runs to the function's end and holds no label, `case` or `goto`, so copying it is safe; `REST` ends in a
`return` at its own level, so it never falls into `L`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close, negate

FAMILY = 'goto_tail_early_exit'
FAMILIES = (FAMILY,)

IF = re.compile(r'(?<![\w.>])if\s*\(')
GUARD = re.compile(r'\s*if\s*\(')
JUMP = re.compile(r'\s*(?:\{\s*goto\s+(?P<braced>\w+)\s*;\s*\}|goto\s+(?P<bare>\w+)\s*;)')
LABEL = re.compile(r'\s*(?P<label>[A-Za-z_]\w*)\s*:(?!:)')
LAST_RETURN = re.compile(r'(?:^|[;{}])\s*(?P<return>return\b(?P<value>[^;{}]*);)\s*\Z')
DECLARES = re.compile(r'^\s*(?:(?:const|volatile|static|register|unsigned|signed|struct|union|enum)\s+)*'
                      r'(?!return\b|goto\b|else\b)[A-Za-z_]\w*(?:\s+|\s*\*+\s*)[A-Za-z_]\w*\s*(?:\[[^\]]*\]\s*)?[=;]')


def _guards(source, clean, start, end):
    """The `if (B) goto L;` tests at the head of a block: ([B], L, where the rest of the block starts)."""
    tests, label, at = [], None, start
    while match := GUARD.match(clean, at, end):
        opening = match.end() - 1
        closing = close(clean, opening)
        jump = closing and JUMP.match(clean, closing, end)
        if not jump:
            break
        target = jump['braced'] or jump['bare']
        if label not in (None, target) or re.compile(r'\s*else\b').match(clean, jump.end()):
            break
        tests.append(source[opening + 1:closing - 1].strip())
        label, at = target, jump.end()
    return tests, label, at


def _loose(condition):
    """Does `condition` bind more loosely than `||` at its own level (`?:`, an assignment or a comma)?"""
    flat = condition
    while (shorter := re.sub(r'\([^()]*\)|\[[^\[\]]*\]', ' ', flat)) != flat:
        flat = shorter
    return re.search(r'[?,]|(?<![=!<>])=(?!=)|(?:<<|>>)=', flat) is not None


def _lines(text, indent):
    """`text`'s own lines moved to `indent`, keeping their depth relative to each other."""
    rows = [row.rstrip() for row in text.strip('\n').split('\n')]
    while rows and not rows[-1].strip():
        rows.pop()
    margin = min((len(row) - len(row.lstrip()) for row in rows if row.strip()), default=0)
    return ''.join(f'{indent}{row[margin:]}\n' if row.strip() else '\n' for row in rows)


def _exit(condition, tail, indent):
    return f'{indent}if ({condition}) {{\n' + _lines(tail, indent + '    ') + f'{indent}}}\n'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body_end = end - 1
    void = re.search(r'\bvoid\s+' + re.escape(name) + r'\s*\(', clean[:opening]) is not None
    result = []
    for statement in IF.finditer(clean, opening + 1, body_end):
        before = clean[opening + 1:statement.start()]
        if before.count('{') != before.count('}') or not re.search(r'(?:\A|[;{}:])\s*\Z', before):
            continue
        cond_open = statement.end() - 1
        cond_close = close(clean, cond_open)
        brace = cond_close and re.compile(r'\s*\{').match(clean, cond_close)
        block_end = brace and close(clean, brace.end() - 1, '{', '}')
        if not block_end:
            continue
        labelled = LABEL.match(clean, block_end, body_end)
        if not labelled:
            continue
        label = labelled['label']
        tests, target, rest_start = _guards(source, clean, brace.end(), block_end - 1)
        if target != label or len(re.findall(rf'\bgoto\s+{label}\b', clean[opening:end])) != len(tests):
            continue
        rest, rest_clean = source[rest_start:block_end - 1], clean[rest_start:block_end - 1]
        last = LAST_RETURN.search(rest_clean)
        if not last or rest_clean[:last.start('return')].count('{') != rest_clean[:last.start('return')].count('}'):
            continue
        tail, tail_clean = source[labelled.end():body_end], clean[labelled.end():body_end]
        if not tail_clean.strip(' \t\n;') or re.search(r'\b(?:case|default|goto)\b|(?m:^\s*[A-Za-z_]\w*\s*:)',
                                                      tail_clean):
            continue
        ends = LAST_RETURN.search(tail_clean)
        if not ends or tail_clean[:ends.start('return')].count('{') != tail_clean[:ends.start('return')].count('}'):
            if not void:
                continue
            tail = tail.rstrip() + '\nreturn;'
            # the added `return;` sits at the tail's own depth
            margin = re.search(r'(?m)^([ \t]*)\S', source[labelled.end():body_end])
            tail = tail[:-len('return;')] + (margin[1] if margin else '    ') + 'return;'
        if void and not last['value'].strip():
            rest = rest[:last.start('return')]
        line = source.rfind('\n', 0, statement.start()) + 1
        indent = source[line:statement.start()]
        if indent.strip():
            continue
        moved = _lines(rest, indent) if rest.strip() else ''
        if any(DECLARES.match(row) for row in rest_clean.split('\n')):
            moved = f'{indent}{{\n' + _lines(rest, indent + '    ') + f'{indent}}}\n'
        condition = source[cond_open + 1:cond_close - 1].strip()
        inverse = negate(condition) or f'!({condition})'
        either = [inverse] + tests
        joined = ' || '.join(f'({part})' if _loose(part) else part for part in either)
        closing_at = source.rfind('\n', 0, body_end) + 1
        for text in (_exit(joined, tail, indent) + moved,
                     ''.join(_exit(part, tail, indent) for part in either) + moved):
            result.append((FAMILY, source[:line] + text + source[closing_at:]))
        break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 300}
