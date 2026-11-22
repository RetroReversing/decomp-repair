"""Split a function's last straight-line run in two with a `do { } while (0)`, so GCC's second scheduler keeps its order.

GCC 2.7.2 (KMC, N64) schedules twice: before register allocation it keeps independent statements in source order, and
again after it, where an add whose result is only stored later is free to float above an unrelated store. The target
of one display-list function had `add p; store p; add q; store q` where every source order gave `add p; add q;
store p; store q`. The loop notes a `do { } while (0)` leaves behind are scheduling boundaries and nothing else
survives into the object, so wrapping the second half of the run in one put the boundary exactly between the two
pairs and the function matched (score 60 -> 0).

Two things make that work, and a proposal here makes both:
- The wrapped part is a *suffix* of the run, ending with the function's last statement (a call). Nothing follows it,
  so no local declared inside could be used after it.
- A global the final call reads is first copied into a local placed *before* the boundary. Left inside, its load
  moves after the boundary, and the target loads it with the first group.
Wrapping alone, or hoisting alone, left the function at the same score; only the pair matched. Both are proposed, and
the pair is proposed directly because a beam that keeps the best three of many equal scores would not reach it.

A run is the plain `expr;` statements just before the last statement, with no call, branch, label or declaration in
them. The last statement is wrapped with them when it is a call. Only MIPS is proposed (the GCC scheduler).
"""
import re

from .csource import _blank, find
from .goto_structure_repairs import blocks, parse

FAMILY = 'scheduling_scope'
FAMILIES = (FAMILY,)
LIMIT = 64
MIN_WRAPPED = 2

_ID = r'[A-Za-z_]\w*'
_COMPOUND = re.compile(r'^\s*(?:if|else|for|while|do|switch|case|default|return|goto|break|continue|asm|__asm__)\b|^\s*\{|^\s*\w+\s*:(?!:)')
_CALL = re.compile(rf'\b{_ID}\s*\(')
_DECLARATION = re.compile(rf'^\s*(?:(?:const|volatile|unsigned|signed|struct|register|static)\s+)*{_ID}(?:\s+|\s*\*+\s*){_ID}\s*(?:=|;|\[)')


def _statements(clean, opening, closing):
    """(start, end) of each top-level statement in the body, a compound statement counted as one."""
    out, i, start, depth = [], opening + 1, None, 0
    while i < closing:
        c = clean[i]
        if start is None and not c.isspace():
            start = i
        if c in '({[':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif c == '}':
            depth -= 1
            if depth == 0 and start is not None:
                tail = re.match(r'\s*(else\b|while\b)', clean[i + 1:closing])
                if not tail:
                    out.append((start, i + 1))
                    start = None
        elif c == ';' and depth == 0 and start is not None:
            out.append((start, i + 1))
            start = None
        i += 1
    return out


def _fresh(source, stem):
    n = 1
    while re.search(rf'\b{stem}_{n}\b', source):
        n += 1
    return f'{stem}_{n}'


def _declared_type(source, upto, symbol):
    """The scalar type a global was declared with (`extern s32 sym;`) before the function, or None."""
    hit = re.search(rf'(?m)^\s*extern\s+((?:(?:const|volatile|unsigned|signed|struct)\s+)*{_ID}(?:\s*\*)*)\s*{symbol}\s*;',
                    source[:upto])
    return re.sub(r'\s+', ' ', hit[1]).strip() if hit and 'volatile' not in hit[1] else None


def _indent(source, start):
    line = source[source.rfind('\n', 0, start) + 1:start]
    return line if not line.strip() else ''


_NARROW_STORE = re.compile(
    rf'\*\s*\(+\s*\(\s*(s16|u16|s8|u8)\s*\*\s*\)\s*\(+\s*'
    rf'\(char\s*\*\s*\)\s*({_ID})\s*\)*\s*\+\s*(0[xX][0-9a-fA-F]+|[0-9]+)'
    r'\s*\)+\s*=(?!=)'
)


def _narrow_store_scopes(source, clean, opening, closing):
    """Isolate a halfword store in a run that also writes byte fields."""
    try:
        function = parse(clean, opening + 1, closing)
    except ValueError:
        return []
    result = []
    for statements in blocks(function):
        for first, middle, last in zip(statements, statements[1:], statements[2:]):
            if any(stmt.kind != 'simple' for stmt in (first, middle, last)):
                continue
            stores = [_NARROW_STORE.match(clean[stmt.start:stmt.end]) for stmt in (first, middle, last)]
            if not all(stores):
                continue
            a, b, c = stores
            if (b[1] not in ('s16', 'u16') or c[1] not in ('s8', 'u8')
                    or not a[2] == b[2] == c[2] or len({a[3], b[3], c[3]}) != 3):
                continue
            original = source[middle.start:middle.end]
            result.append((FAMILY, source[:middle.start] + 'do { ' + original + ' } while (0);'
                           + source[middle.end:]))
            if len(result) == 8:
                return result
    return result


def variants(source, name, arch='mips', asm='', header=''):
    """Proposals: the run's second half in `do { } while (0)`, with and without the final call's globals hoisted."""
    if arch != 'mips':
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    closing = clean.rfind('}', 0, span[1])
    if opening < 0 or closing < opening or re.search(r'^\s*#', clean[span[0]:span[1]], re.M):
        return []
    # An isolated comparison can need a boundary even inside an existing scope.
    # Only wrap assignments to a scalar local; the expression is evaluated once.
    comparison = re.compile(rf'(?:^|[;{{}}])\s*(?P<assignment>{_ID}\s*=\s*(?:\({_ID}\)\s*)?\(\s*{_ID}\s*(?:<=|>=|<|>|==|!=)\s*{_ID}\s*\)\s*;)', re.M)
    out = [(FAMILY, source[:m.start('assignment')] + 'do { ' + source[m.start('assignment'):m.end('assignment')] + ' } while (0);' + source[m.end('assignment'):])
           for m in comparison.finditer(clean, opening + 1, closing)][:LIMIT]
    out = (out + _narrow_store_scopes(source, clean, opening, closing))[:LIMIT]
    if re.search(r'\bvolatile\b', clean[span[0]:span[1]]):
        return out
    statements = _statements(clean, opening, closing)
    if len(statements) < MIN_WRAPPED + 1:
        return out
    text = [clean[a:b] for a, b in statements]
    last = len(statements)
    if _CALL.search(text[-1]) and not _COMPOUND.match(text[-1]) and not _DECLARATION.match(text[-1]):
        last -= 1  # the final call belongs to the run's last group; the plain statements before it are the run
    first = last
    while first > 0 and not _COMPOUND.match(text[first - 1]) and not _CALL.search(text[first - 1]) \
            and not _DECLARATION.match(text[first - 1]):
        first -= 1
    end = len(statements)
    run = range(first, end)
    call = text[-1] if last < end else ''
    symbols = []
    if call:
        args = call[call.index('(') + 1:call.rindex(')')]
        for arg in (a.strip() for a in args.split(',')):
            if re.fullmatch(_ID, arg) and arg not in symbols and _declared_type(source, span[0], arg):
                symbols.append(arg)
    for k in run:
        if end - k < MIN_WRAPPED:
            break
        a, b = statements[k][0], statements[-1][1]
        indent = _indent(source, a)
        body = source[a:b]
        wrapped = f'do {{\n{indent}    ' + re.sub(r'\n(?=[ \t]*\S)', '\n    ', body) + f'\n{indent}}} while (0);'
        out.append((FAMILY, source[:a] + wrapped + source[b:]))
        for symbol in symbols:
            for h in range(first, k + 1):
                temp = _fresh(source, 'repair_scope')
                kind = _declared_type(source, span[0], symbol)
                call_a = statements[-1][0]
                new_call = re.sub(rf'(?<![\w.>]){symbol}(?![\w(])', temp, source[call_a:b])
                new_body = source[a:call_a] + new_call
                wrapped = f'do {{\n{indent}    ' + re.sub(r'\n(?=[ \t]*\S)', '\n    ', new_body) + f'\n{indent}}} while (0);'
                hoist_at = statements[h][0]
                hoist = f'{temp} = {symbol};\n{_indent(source, hoist_at)}'
                src = source[:hoist_at] + hoist + source[hoist_at:a] + wrapped + source[b:]
                if h == k:
                    src = source[:hoist_at] + hoist + wrapped + source[b:]
                body_open = src.index('{', src.index(name, find(src, name)[0]))
                src = src[:body_open + 1] + f'\n    {kind} {temp};' + src[body_open + 1:]
                out.append((FAMILY, src))
    seen, unique = set(), []
    for item in out:
        if item[1] not in seen and item[1] != source:
            seen.add(item[1])
            unique.append(item)
    return unique[:LIMIT]
