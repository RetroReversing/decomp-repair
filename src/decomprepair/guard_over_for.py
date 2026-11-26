"""A guard that repeats a `for` loop's entry test, with the loop's invariant reads named ahead of it, written as one `for`.

`i = 0; if (n[2] != 0) { a = A; b = B; for (; i < n[2]; i++) { .. a .. b .. } }` is a hand-made copy of what the compiler
does itself: jump.c copies a `for` loop's entry test in front of the loop and loop.c moves the invariant loads into the
preheader behind that test. Written out, the `for` still gets its own copy of the test, so the guard is there twice, and
without the guard the named reads come before the test. The source is `for (i = 0; i < n[2]; i++)` with the reads in the
body.

On a 45-instruction N64 table search (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O1`): 350 -> 0. Each half alone did not
help (guard dropped, reads still named: 390; reads inlined under the guard: 350), so the combined child is the one that
matters.

Offered when the block under `if (X != 0)` / `if (X)` / `if (0 < X)` holds only `v = G;` statements (G a plain name no
statement writes) and one `for (; i < X; i++)` with a braced body that makes no call and writes only the function's locals, `i = 0;` stands
right before the guard or first in its block, each `v` is read only in the loop, and, for the `!= 0` forms, X is declared
unsigned (so the test is the loop's own `0 < X`).
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, locals_for, view
from .pattern_repairs import close

FAMILY = 'guard_over_for'
FAMILIES = (FAMILY,)
LIMIT = 4
_UNSIGNED = r'(?:u8|u16|u32|unsigned(?:\s+(?:char|short|int|long))?)'
_GUARD = re.compile(r'\bif\s*\(')
_ASSIGN = re.compile(rf'\s*({IDENT})\s*=(?!=)\s*({IDENT})\s*;')
_TEST = re.compile(r'(?:0\s*<\s*(?P<above>.+)|(?P<x>.+?)\s*(?:>\s*0|!=\s*0)?)', re.S)


def _unsigned(context, expression):
    """Whether the thing read by `expression` is declared unsigned: `p[k]`, `p->f`, a name, or a `(u8)` cast."""
    if re.match(rf'\(\s*{_UNSIGNED}\s*\)', expression):
        return True
    member = re.search(rf'(?:->|\.)\s*({IDENT})\s*$', expression)
    base = member or re.fullmatch(rf'\s*\*?\s*({IDENT})\s*(?:\[[^\]]*\])?\s*', expression)
    return bool(base and re.search(rf'\b{_UNSIGNED}\s*\*?\s*\b{re.escape(base[1])}\b\s*(?:\[[^\]]*\]\s*)?[;,)]', context))


def _written(text, name):
    escaped = re.escape(name)
    return bool(re.search(rf'(?<![\w.>])&?\b{escaped}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{escaped}\b|\b{escaped}\s*(?:\+\+|--)'
                          rf'|(?<![&\w])&\s*{escaped}\b', text))


def _may_store(body, local_names):
    """Whether the body may change memory the named reads came from: a call, or a write of anything but a function local."""
    if re.search(rf'\b(?!if\b|for\b|while\b|switch\b|sizeof\b){IDENT}\s*\(|\+\+|--', body):
        return True
    for hit in re.finditer(r'(?<![=!<>])=(?!=)|(?:<<|>>)=', body):
        left = re.search(rf'[{{}};)]\s*({IDENT})\s*(?:[-+*/%&|^]|<<|>>)?$', body[:hit.start()])
        if not left or left[1] not in local_names:
            return True
    return False


def _only_in(clean, low, high, local, assigned_end, body_start, body_end):
    """Whether, besides its declaration and the one assignment before the loop, `local` is only read, inside the loop body."""
    declaration = rf'(?m)^[ \t]*(?!return\b)[A-Za-z_]\w*[ \t]+{re.escape(local)}[ \t]*;'
    text = re.sub(declaration, lambda m: ' ' * len(m[0]), clean[low:high])
    uses = [low + m.start() for m in re.finditer(rf'(?<![\w.>])\b{re.escape(local)}\b', text)]
    outside = [at for at in uses if not body_start <= at < body_end]
    return len(outside) == 1 and outside[0] < assigned_end and len(uses) > 1


def _children(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', part.body):
        return []
    clean, context = part.clean, _blank(header) + '\n' + _blank(source)
    result = []
    for guard in _GUARD.finditer(clean, part.opening, part.end):
        paren = guard.end() - 1
        after = close(clean, paren)
        if after is None:
            continue
        opening = after + len(clean[after:]) - len(clean[after:].lstrip())
        if clean[opening:opening + 1] != '{':
            continue
        end = close(clean, opening, '{', '}')
        if end is None or re.match(r'\s*else\b', clean[end:]):
            continue
        condition = clean[paren + 1:after - 1].strip()
        test = _TEST.fullmatch(condition)
        if not test:
            continue
        bound = (test['above'] or test['x']).strip()
        positive = bool(test['above']) or bool(re.search(r'>\s*0$', condition))
        if not positive and not _unsigned(context, bound):
            continue
        inner = clean[opening + 1:end - 1]
        reads, at, start_value = [], 0, None
        while True:
            hit = _ASSIGN.match(inner, at)
            zero = re.compile(rf'\s*({IDENT})\s*=\s*0\s*;').match(inner, at)
            if zero:
                start_value, at = zero[1], zero.end()
            elif hit:
                reads.append((hit[1], hit[2], opening + 1 + hit.start(1), opening + 1 + hit.end()))
                at = hit.end()
            else:
                break
        loop = re.compile(r'\s*for\s*\(').match(inner, at)
        if not loop:
            continue
        head = opening + 1 + loop.end() - 1
        head_end = close(clean, head)
        if head_end is None:
            continue
        pieces = clean[head + 1:head_end - 1].split(';')
        if len(pieces) != 3:
            continue
        initial, condition_in, step = (piece.strip() for piece in pieces)
        counter = re.fullmatch(rf'({IDENT})\s*\+\+|\+\+\s*({IDENT})', step)
        if not counter:
            continue
        counter = counter[1] or counter[2]
        squeeze = lambda text: re.sub(r'\s+', '', text)
        if squeeze(condition_in) != squeeze(f'{counter}<{bound}'):
            continue
        body_start = head_end + len(clean[head_end:]) - len(clean[head_end:].lstrip())
        if clean[body_start:body_start + 1] != '{':
            continue
        body_end = close(clean, body_start, '{', '}')
        if body_end is None or clean[body_end:end - 1].strip():
            continue
        body = clean[body_start:body_end]
        if _may_store(body, {d['name'] for d in locals_for(part)}):
            continue
        low = part.opening + 1
        before = clean[low:guard.start()]
        zero_before = re.search(rf'(?<![\w.>])\b{re.escape(counter)}\s*=\s*0\s*;\s*$', before)
        if initial:
            if squeeze(initial) != f'{counter}=0':
                continue
            zero_before = None
        elif not (zero_before or start_value == counter) or (start_value and start_value != counter):
            continue
        names = [r[0] for r in reads]
        if len(set(names)) != len(names) or counter in names:
            continue
        if not all(_only_in(clean, low, part.end, local, finish, body_start, body_end)
                   and not _written(clean[low:part.end], value) for local, value, _, finish in reads):
            continue
        text = source[body_start:body_end]
        for local, value, _, _ in reads:
            blank = _blank(text)
            for use in reversed(list(re.finditer(rf'(?<![\w.>])\b{re.escape(local)}\b', blank))):
                text = text[:use.start()] + value + text[use.end():]
        limit = source[head + 1:head_end - 1].split(';')[1].split('<', 1)[1].strip()
        loop_text = f'for ({counter} = 0; {counter} < {limit}; {step}) {text}'
        replace_from = low + zero_before.start() if zero_before else guard.start()
        edits = [(replace_from, end, loop_text)]
        for local, _, _, _ in reads:
            declaration = re.search(rf'(?m)^[ \t]*(?!return\b)[A-Za-z_]\w*[ \t]+{re.escape(local)}[ \t]*;[ \t]*\n', clean[low:replace_from])
            if declaration:
                edits.append((low + declaration.start(), low + declaration.end(), ''))
        result.append((FAMILY, edit(source, edits)))
    return result[:LIMIT]


def variants(source, name, header=''):
    return [(family, text) for family, text in _children(source, name, header) if text != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
