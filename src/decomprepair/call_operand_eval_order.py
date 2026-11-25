"""The two operands of an assignment's sum or difference written the other way round, when each one makes a call.

GCC (2.7.2 and SN64's 2.8.1, `-O2`, N64) expands a binary expression's operands in the order they are written, so the
calls inside them are made in that order: `x = (g(a) * u) - (h(a) * v);` calls `g` first. Nothing later moves a call
across another, so a target that calls `h` first was written with `h`'s operand first. A 1585-instruction collision
routine rotated a point with two `sins`/`coss` pairs; the second pair is called cosine first in the target, and
`dz = -((s32)(dx * coss(a)) >> 15) + ((s32)(dz * sins(a)) >> 15);` (the same value as the draft's difference) put the
calls, the products' registers and the `subu` in the target's order (3827 -> 3257 together with the rows that followed).

Rewrites the top-level `+`, `-` or `*` of an assignment's right-hand side (`lhs = A op B;`, also `+=`/`-=`), when both
`A` and `B` contain a call: `A + B` -> `B + A`, `A * B` -> `B * A`, `A - B` -> `-(B) + A`. Each is the same value for
integers (wrapping) and for floats (negation is exact; addition and multiplication commute). Bounded to `LIMIT`
children, one site each, in text order.
"""
import re

FAMILY = 'call_operand_eval_order'
FAMILIES = (FAMILY,)
LIMIT = 12
_ASSIGN = re.compile(r'(?<![=!<>+\-*/%&|^])(?P<op>[+\-]?=)(?!=)')
_CALL = re.compile(r'\b(?P<name>[A-Za-z_]\w*)\s*\(')
_NOT_CALLS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'do'}
_OPERAND_END = re.compile(r'[\w)\].]')


def _has_call(text):
    for found in _CALL.finditer(text):
        name = found['name']
        if name in _NOT_CALLS or name.isupper():  # a keyword, or a macro such as M2C_FIELD
            continue
        return True
    return False


def _strip_outer(text):
    """`(A - B)` -> `A - B` when the outer parentheses enclose the whole text."""
    body = text.strip()
    while body.startswith('(') and body.endswith(')'):
        depth = 0
        for i, ch in enumerate(body):
            depth += ch == '('
            depth -= ch == ')'
            if depth == 0 and i != len(body) - 1:
                return body
        body = body[1:-1].strip()
    return body


def _split(expr):
    """The last top-level binary `+`/`-` of EXPR, else its last top-level `*`: (left, op, right) or None."""
    for wanted in ('+-', '*'):
        depth = 0
        found = None
        i = 0
        while i < len(expr):
            ch = expr[i]
            if ch in '([':
                depth += 1
            elif ch in ')]':
                depth -= 1
            elif depth == 0 and ch in wanted:
                nxt = expr[i + 1:i + 2]
                prev = expr[:i].rstrip()
                pair = expr[i - 1:i + 1] if i else ''
                if nxt in ('+', '-', '=', '>') or pair in ('++', '--', '->'):
                    i += 2 if nxt in ('+', '-', '=', '>') else 1
                    continue
                # binary only: something that ends an operand comes before it (not `= -x`, not `1.0e-5`)
                if prev and _OPERAND_END.match(prev[-1]) and not re.search(r'\d[eE]$', prev):
                    found = i
            i += 1
        if found is not None:
            left, right = expr[:found].strip(), expr[found + 1:].strip()
            if left and right:
                return left, expr[found], right
    return None


def _statements(source):
    """(start, end) of each `lhs op= rhs;` statement's right-hand side, with its assignment operator."""
    for found in _ASSIGN.finditer(source):
        start = found.end()
        depth = 0
        i = start
        while i < len(source):
            ch = source[i]
            if ch in '([{':
                depth += 1
            elif ch in ')]}':
                depth -= 1
                if depth < 0:
                    break
            elif ch == ';' and depth == 0:
                yield start, i
                break
            elif ch in '{}' or (ch == ',' and depth == 0):
                break
            i += 1


def variants(source, name, header=''):
    out = []
    for start, end in _statements(source):
        rhs = source[start:end]
        parts = _split(_strip_outer(rhs))
        if parts is None:
            continue
        left, op, right = parts
        if not (_has_call(left) and _has_call(right)):
            continue
        if op == '-':
            swapped = f'-({right}) + {left}'
        else:
            swapped = f'{right} {op} {left}'
        lead = rhs[:len(rhs) - len(rhs.lstrip())]
        out.append((FAMILY, source[:start] + lead + swapped + source[end:]))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
