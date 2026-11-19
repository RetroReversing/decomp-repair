"""Small rewrites that change only which registers gcc 2.7.2 chooses, for a near miss off by a register or two.

In KMC GCC 2.7.2 a `plus` (or any commutative operation) of two registers keeps the operand order the C wrote
through every pass to allocation, and the allocator gives the result the register of an operand that dies there,
preferring the first. Which operand dies depends on statement order and on the first scheduling pass, which may
move an independent store above the operation. So the levers are: the operand order of a commutative operation,
the order of two independent statements, a compound assignment written out either way, and a declaration's place
(the order pseudos are created in, which breaks allocation ties). Each proposal is one lever; a deep pass chains
them. They keep the meaning: operands of a commutative operator, statements that neither read nor write what the
other writes, `x op= e` as `x = x op e`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'allocation_lever'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
COMMUTATIVE = '+*&|^'
STATEMENT = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<body>[^\n{};]*[^\s{};][^\n{};]*;)[ \t]*$')
ASSIGN = re.compile(r'^(?P<lhs>' + IDENT + r'|\*?\(?[^=]*?\)?)\s*(?P<op>[-+*/&|^]|<<|>>)?=(?!=)\s*(?P<rhs>.+);$')
LIMIT = 24


def _operands(text):
    """(start, end) of each top-level operand around a single commutative operator in `text`, or None."""
    depth, cuts = 0, []
    for i, ch in enumerate(text):
        depth += (ch in '([') - (ch in ')]')
        if depth == 0 and ch in COMMUTATIVE:
            before = text[i - 1] if i else ''
            after = text[i + 1] if i + 1 < len(text) else ''
            if ch in '&|' and (after == ch or before == ch):
                continue  # && and ||
            if ch == '*' and not re.search(r'[\w)\]]\s*$', text[:i]):
                continue  # a dereference or a pointer cast, not a product
            if ch in '+-' and (after in '+=' or before == ch):
                continue
            if after == '=':
                continue
            cuts.append((i, ch))
    return cuts


def _swaps(expr):
    """`expr` with the two operands of one top-level commutative operator swapped, for each such operator alone."""
    out = []
    cuts = _operands(expr)
    if len(cuts) != 1:
        # several operators at one level (`a + b + c`): swap neighbours of the same operator, left to right
        pieces, last = [], 0
        for i, _ in cuts:
            pieces.append(expr[last:i])
            last = i + 1
        pieces.append(expr[last:])
        ops = [ch for _, ch in cuts]
        for k in range(len(ops)):
            if k + 1 < len(pieces) and (k == 0 or ops[k - 1] == ops[k]) and (k + 1 == len(ops) or ops[k + 1] == ops[k]):
                swapped = pieces[:]
                swapped[k], swapped[k + 1] = swapped[k + 1].strip(), swapped[k].strip()
                text = ''.join(p if j == 0 else f' {ops[j - 1]} {p.strip()}' for j, p in enumerate(swapped)).strip()
                if all(o == ops[0] for o in ops) and text != expr.strip():
                    out.append(text)
        return out
    i, ch = cuts[0]
    a, b = expr[:i].strip(), expr[i + 1:].strip()
    if a and b:
        out.append(f'{b} {ch} {a}')
    # and inside a parenthesised operand
    for side, other, left in ((a, b, True), (b, a, False)):
        if side.startswith('(') and close(side, 0) == len(side):
            for inner in _swaps(side[1:-1]):
                out.append(f'({inner}) {ch} {other}' if left else f'{other} {ch} ({inner})')
    return out


def _names(text):
    return set(re.findall(r'(?<![\w.>])' + IDENT, text))


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []

    def emit(text):
        if text != source and text not in [t for _, t in result] and len(result) < LIMIT:
            result.append((FAMILY, text))

    statements = [m for m in STATEMENT.finditer(clean, opening + 1, end)
                  if not re.match(r'\s*(?:return|goto|break|continue|case|default|if|for|while|do|else)\b', m['body'])]
    declarations = [m for m in statements if re.match(r'\s*(?:(?:unsigned|signed|const|volatile|register)\s+)*'
                                                       + IDENT + r'[\s*]+' + IDENT + r'\s*;$', m['body'])]
    for m in statements:
        if m in declarations:
            continue
        body = source[m.start('body'):m.end('body')]
        assign = ASSIGN.match(body)
        if not assign:
            continue
        rhs = assign['rhs']
        for swapped in _swaps(rhs):
            emit(source[:m.start('body')] + body[:assign.start('rhs')] + swapped + ';' + source[m.end('body'):])
        lhs, op = assign['lhs'].strip(), assign['op']
        if op and op in COMMUTATIVE + '-/' and re.fullmatch(IDENT, lhs):
            for written in (f'{lhs} = {lhs} {op} ({rhs})', f'{lhs} = ({rhs}) {op} {lhs}' if op in COMMUTATIVE else None):
                if written:
                    emit(source[:m.start('body')] + written + ';' + source[m.end('body'):])
    # neighbouring statements that neither read nor write what the other writes
    for first, second in zip(statements, statements[1:]):
        if first in declarations or second in declarations:
            continue
        if clean[first.end():second.start()].strip():
            continue
        a, b = ASSIGN.match(first['body'].strip()), ASSIGN.match(second['body'].strip())
        if not a or not b or re.search(IDENT + r'\s*\(', first['body'] + second['body']):
            continue
        wa, wb = _names(a['lhs']), _names(b['lhs'])
        if wa & _names(second['body']) or wb & _names(first['body']):
            continue
        emit(source[:first.start()] + source[second.start():second.end()] + '\n' + source[first.start():first.end()]
             + source[second.end():])
    # a declaration moved first: pseudos are numbered in creation order, which breaks allocation ties
    for m in declarations[1:]:
        top = declarations[0]
        line_end = clean.find('\n', m.end()) + 1
        line = source[m.start():line_end]
        emit(source[:top.start()] + line + source[top.start():m.start()] + source[line_end:])
    return result
