"""m2c's copy before a nested guard, sunk into the arms the source wrote it in.

When a value is copied to another variable on every way out of a guarded block, m2c writes the copy twice and joins
the paths with a label:

    if (P != NULL) {
        var_v0 = var_s3;
        if (Q != NULL) {
            BODY;
            goto block_9;
        }
    } else {
block_9:
        var_v0 = var_s3;
    }
    if (var_v0 == 0) { ... }

The first copy is a real instruction placed before the inner test, so the compiler keeps the value in a register
that is live across it and gives the copy `$v1`. GCC 2.7.2 (an N64 game's own build) wrote the copy after the
branches, in `$v0`, and its delay slot took the copy from the join. The source that gives that is the two guards as
one test, with the copy at the end of each arm:

    if (P != NULL && Q != NULL) {
        BODY;
        var_v0 = var_s3;
    } else {
        var_v0 = var_s3;
    }

The copy has to stay on both arms: with one definition the compiler folds it into its source and the move is gone.
Seen on a function that was 15 points from exact with only `$v0`/`$v1` differing, exact with this shape. Offered
when both copies are the same statement and nothing else jumps to the label.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'join_copy_sink'
FAMILIES = (FAMILY,)


def _condition(clean, source, at):
    """(condition text, index after its `)`) of the `(` at `at`."""
    end = close(clean, at, '(', ')')
    return (source[at + 1:end - 1].strip(), end) if end else (None, None)


def _joined(cond):
    """A condition fit to sit beside `&&`: parenthesised when it has a lower-precedence operator."""
    depth = 0
    for match in re.finditer(r'[()]|\|\||\?', cond):
        depth += (match[0] == '(') - (match[0] == ')')
        if depth == 0 and match[0] not in '()':
            return f'({cond})'
    return cond


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    result = []
    for guard in re.finditer(r'\bif\s*\(', clean[span[0]:span[1]]):
        at = span[0] + guard.start()
        outer, after = _condition(clean, source, span[0] + guard.end() - 1)
        block = re.compile(r'\s*\{').match(clean, after) if outer else None
        if not block:
            continue
        block_open = block.end() - 1
        block_end = close(clean, block_open, '{', '}')
        other = re.compile(r'\s*else\s*\{').match(clean, block_end) if block_end else None
        if not other:
            continue
        other_open = other.end() - 1
        other_end = close(clean, other_open, '{', '}')
        if not other_end:
            continue
        # the first arm: a copy, then `if (Q) { BODY goto L; }` and nothing else
        first = re.compile(r'\s*(?P<copy>[^;{}]+;)\s*if\s*\(').match(clean, block_open + 1)
        if not first:
            continue
        inner, inner_after = _condition(clean, source, first.end() - 1)
        inner_block = re.compile(r'\s*\{').match(clean, inner_after) if inner else None
        if not inner_block:
            continue
        inner_open = inner_block.end() - 1
        inner_end = close(clean, inner_open, '{', '}')
        if not inner_end or clean[inner_end:block_end - 1].strip():
            continue
        jump = re.compile(r'\bgoto\s+(\w+)\s*;\s*$').search(clean, inner_open, inner_end - 1)
        if not jump:
            continue
        label = jump[1]
        # the second arm: the label, then the same copy
        landing = re.compile(r'\s*' + label + r':\s*(?P<copy>[^;{}]+;)\s*$').match(clean, other_open + 1, other_end - 1)
        copy = ' '.join(clean[first.start('copy'):first.end('copy')].split())
        if not landing or ' '.join(clean[landing.start('copy'):landing.end('copy')].split()) != copy:
            continue
        if len(re.findall(r'\bgoto\s+' + label + r'\s*;', clean[span[0]:span[1]])) != 1:
            continue
        line = clean.rfind('\n', 0, at) + 1
        ind = re.match(r'[ \t]*', clean[line:])[0]
        body = source[inner_open + 1:jump.start()].rstrip()
        body = ''.join(l[4:] if l.startswith(ind + '        ') else l for l in body.splitlines(keepends=True))
        text = ' '.join(source[first.start('copy'):first.end('copy')].split())
        replacement = (f'if ({_joined(outer)} && {_joined(inner)}) {{' + body.rstrip() + '\n'
                       f'{ind}    {text}\n{ind}}} else {{\n{ind}    {text}\n{ind}}}')
        result.append((FAMILY, source[:at] + replacement + source[other_end:]))
    return result[:2]
