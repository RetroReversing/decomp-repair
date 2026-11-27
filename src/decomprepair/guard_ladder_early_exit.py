"""A ladder of nested guards that all fail to one labelled tail, written as the early exit those guards were.

m2c writes a function that stores a "nothing to do" value and returns when any of several tests fails as nested
`if`s whose failing paths `goto` labels after the outermost one:

    if (actor != NULL) {
        if (mode == 0) {
            if (actor->state != 0xFFFF) {
                ...
                    REST;
                    return;
                ...
            }
            goto block_6;
        }
        goto block_7;
    }
    block_6:
    block_7:
    timer = 0;

SN GCC lays the work out first and the shared tail after it. The game wrote the tail first,
`if (actor == NULL || mode != 0 || actor->state == 0xFFFF) { timer = 0; return; }` with the work after it, so the
target branches to a `j end; sw` placed before the work. On an 85-instruction N64 function this one edit took the
saved best from 720 to 0. `goto_tail_early_exit` does the same for a single `if` with its guards at its head; this
walks any depth of nesting.

Each level may start with `if (B) goto L;` guards, then either `if (C) { <next level> } goto L;` (a failing `C`
jumps to the tail) or the work, which ends in a `return`. The outermost `if` falls into the labels. The tail runs to
the function's end and holds no label, `case` or `goto`, so copying it is safe.

Variants: the tests joined with `||` in one `if`, or one `if` each (cross-jumping merges the tails).
"""
import re

from .csource import _blank, find
from .goto_tail_early_exit import DECLARES, JUMP, LAST_RETURN, _lines, _loose
from .pattern_repairs import close, negate

FAMILY = 'guard_ladder_early_exit'
FAMILIES = (FAMILY,)

IF = re.compile(r'(?<![\w.>])if\s*\(')
HEAD = re.compile(r'\s*if\s*\(')
ELSE = re.compile(r'\s*else\b')
BRACE = re.compile(r'\s*\{')
LABELS = re.compile(r'(?:\s*;)*(?:\s*(?!(?:default|case)\b)[A-Za-z_]\w*\s*:(?!:)(?:\s*;)*)+')
GOTO = re.compile(r'\s*goto\s+(\w+)\s*;')
CAST = re.compile(r'\(\s*[A-Za-z_]\w*(?:\s*\*+)?\s*\)')


def _split(condition, operator):
    """`condition` cut at its own level's `operator` (`&&` or `||`)."""
    depth, last, parts = 0, 0, []
    for match in re.finditer(r'[(\[]|[)\]]|&&|\|\|', condition):
        token = match[0]
        if token in '([':
            depth += 1
        elif token in ')]':
            depth -= 1
        elif depth == 0 and token == operator:
            parts.append(condition[last:match.start()])
            last = match.end()
    return [part.strip() for part in parts + [condition[last:]]]


def _unwrap(condition):
    """`condition` without parentheses that surround all of it."""
    while condition.startswith('(') and close(condition, 0) == len(condition):
        condition = condition[1:-1].strip()
    return condition


def _failures(condition):
    """The tests that, any one true, make `condition` false."""
    condition = _unwrap(condition)
    if len(_split(condition, '||')) > 1:
        return [f'!({condition})']
    result = []
    for part in _split(condition, '&&'):
        part = _unwrap(part)
        if len(_split(part, '||')) > 1 or len(_split(part, '&&')) > 1:
            result += [f'!({part})']
        elif inverse := negate(part):
            result.append(inverse)
        elif part.startswith('!') and (rest := part[1:].strip()).startswith('(') and close(rest, 0) == len(rest):
            result.append(rest[1:-1].strip())
        elif re.fullmatch(r'![\w.>\[\]-]+', part):
            result.append(part[1:])
        elif re.fullmatch(r'[A-Za-z_][\w.>\[\]-]*', part):
            result.append('!' + part)
        else:
            result.append(f'!({part})')
    return result


def _if(source, clean, at, end):
    """The `if (...) {...}` at `at`: (condition, body start, body end, where it stops), or None."""
    match = HEAD.match(clean, at, end)
    if not match:
        return None
    cond_close = close(clean, match.end() - 1)
    brace = cond_close and BRACE.match(clean, cond_close, end)
    block_end = brace and close(clean, brace.end() - 1, '{', '}')
    if not block_end or block_end > end or ELSE.match(clean, block_end, end):
        return None
    return source[match.end():cond_close - 1].strip(), brace.end(), block_end - 1, block_end


def _level(source, clean, start, end, labels):
    """One level of the ladder between `start` and `end`: (failing tests, jumps used, work start, work end, depth)."""
    tests, jumps, at = [], 0, start
    while match := HEAD.match(clean, at, end):
        cond_close = close(clean, match.end() - 1)
        jump = cond_close and JUMP.match(clean, cond_close, end)
        if not jump or (jump['braced'] or jump['bare']) not in labels or ELSE.match(clean, jump.end(), end):
            break
        tests.append(source[match.end():cond_close - 1].strip())
        jumps, at = jumps + 1, jump.end()
    nested = _if(source, clean, at, end)
    if nested:
        condition, inner_start, inner_end, stop = nested
        after = GOTO.match(clean, stop, end)
        if after and after[1] in labels and not clean[after.end():end].strip():
            inner = _level(source, clean, inner_start, inner_end, labels)
            if inner:
                return (tests + _failures(condition) + inner[0], jumps + 1 + inner[1], inner[2], inner[3],
                        inner[4] + 1)
    work = clean[at:end]
    last = LAST_RETURN.search(work)
    if not last or work[:last.start('return')].count('{') != work[:last.start('return')].count('}'):
        return None
    return tests, jumps, at, end, 0


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
    for statement in IF.finditer(clean, opening + 1, body_end):
        before = clean[opening + 1:statement.start()]
        if before.count('{') != before.count('}') or not re.search(r'(?:\A|[;{}])\s*\Z', before):
            continue
        outer = _if(source, clean, statement.start(), body_end)
        if not outer:
            continue
        condition, block_start, block_end, stop = outer
        labelled = LABELS.match(clean, stop, body_end)
        if not labelled:
            continue
        labels = set(re.findall(r'([A-Za-z_]\w*)\s*:', labelled[0]))
        level = _level(source, clean, block_start, block_end, labels)
        if not level or not level[4]:
            continue
        tests, jumps, work_start, work_end, _ = level
        if jumps != sum(len(re.findall(rf'\bgoto\s+{label}\b', clean[opening:end])) for label in labels):
            continue
        tail, tail_clean = source[labelled.end():body_end], clean[labelled.end():body_end]
        if not tail_clean.strip(' \t\n;') or re.search(r'\b(?:case|default|goto)\b|(?m:^\s*[A-Za-z_]\w*\s*:)',
                                                      tail_clean):
            continue
        ends = LAST_RETURN.search(tail_clean)
        if not ends or tail_clean[:ends.start('return')].count('{') != tail_clean[:ends.start('return')].count('}'):
            if not void:
                continue
            margin = re.search(r'(?m)^([ \t]*)\S', tail)
            tail = tail.rstrip() + '\n' + (margin[1] if margin else '    ') + 'return;'
        line = source.rfind('\n', 0, statement.start()) + 1
        indent = source[line:statement.start()]
        if indent.strip():
            continue
        work, work_clean = source[work_start:work_end], clean[work_start:work_end]
        if void:
            last = LAST_RETURN.search(work_clean)
            if not last['value'].strip():
                work = work[:last.start('return')]
        moved = _lines(work, indent) if work.strip() else ''
        if any(DECLARES.match(row) for row in work_clean.split('\n')):
            moved = f'{indent}{{\n' + _lines(work, indent + '    ') + f'{indent}}}\n'
        either = _failures(condition) + tests
        joined = ' || '.join(f'({part})' if _loose(part) and not CAST.fullmatch(part) else part for part in either)
        closing_at = source.rfind('\n', 0, body_end) + 1
        result = []
        for texts in ([joined], either):
            exits = ''.join(f'{indent}if ({text}) {{\n' + _lines(tail, indent + '    ') + f'{indent}}}\n'
                            for text in texts)
            result.append((FAMILY, source[:line] + exits + moved + source[closing_at:]))
        return result
    return []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 300}
