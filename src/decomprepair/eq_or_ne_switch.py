"""m2c's `(v == K1) || (v != K2)` test, written as the switch with a shared `default` that it came from.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) projectile update of 2,503 instructions. The target
branches `beq v, K1 -> A; beq v, K2 -> B;` and falls through into A: a switch whose `case K1` and `default` share
one body. m2c reads the two compares as

    } else if ((v == 1) || (v != 2)) {
        A
    } else {
        B
    }

and gcc folds that `||` of two simple compares into `xori`/`sltu`/`or` and one branch. As
`switch (v) { default: case 1: A break; case 2: B break; }` the function went 23368 -> 21908 (the same bodies with
`if (v == 1) A else if (v == 2) B else A`: 22438).

eq_or_ne_switch
    An `if` or `else if` whose whole test is `(v == K1) || (v != K2)` (either order, K1 != K2) with an `else`, becomes
    `switch (v)` with `default: case K1:` taking the `if` body and `case K2:` the `else` body (an `else if` becomes an
    `else { switch ... }`). Children: the shared body first, and the `case K2` body first. The exact judge decides.
"""
import re

FAMILY = 'eq_or_ne_switch'
FAMILIES = (FAMILY,)
LIMIT = 8

_ID = r'[A-Za-z_][\w.\[\]>-]*'
_NUM = r'-?(?:0[xX][0-9A-Fa-f]+|\d+)'
_IF = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<lead>\}} else )?if \((?:'
    rf'\((?P<v1>{_ID}) == (?P<k1>{_NUM})\) \|\| \((?P=v1) != (?P<k2>{_NUM})\)'
    rf'|\((?P<v2>{_ID}) != (?P<k4>{_NUM})\) \|\| \((?P=v2) == (?P<k3>{_NUM})\)'
    rf')\) \{{[ \t]*\n')


def _block(source, start):
    """(index of the closing brace, index after its line) for a block whose body starts at `start`."""
    depth = 1
    for found in re.finditer(r'[{}]', source[start:]):
        depth += 1 if found.group() == '{' else -1
        if depth == 0:
            close = start + found.start()
            return close, source.find('\n', close) + 1 or len(source)
    return -1, -1


def _indent(body, extra):
    return ''.join(extra + line + '\n' if line.strip() else '\n' for line in body.rstrip('\n').split('\n'))


def _rewrites(source, head):
    variable = head.group('v1') or head.group('v2')
    k_eq = head.group('k1') or head.group('k3')
    k_ne = head.group('k2') or head.group('k4')
    if int(k_eq, 0) == int(k_ne, 0):
        return []
    then_close, _ = _block(source, head.end())
    if then_close < 0:
        return []
    rest = source[then_close:]
    found = re.match(r'\}[ \t]*else[ \t]*\{[ \t]*\n', rest)
    if not found:
        return []
    else_start = then_close + found.end()
    else_close, end = _block(source, else_start)
    if else_close < 0:
        return []
    then_body = source[head.end():source.rfind('\n', 0, then_close) + 1]
    else_body = source[else_start:source.rfind('\n', 0, else_close) + 1]
    if re.search(r'\bbreak\b', then_body + else_body):
        return []
    indent = head.group('indent')
    nested = head.group('lead') is not None
    pad = indent + ('    ' if nested else '')
    extra = '    ' if nested else ''
    case_a = _indent(then_body, extra) + f'{pad}    break;\n'
    case_b = _indent(else_body, extra) + f'{pad}    break;\n'
    out = []
    for default_first in (True, False):
        if default_first:
            cases = f'{pad}default:\n{pad}case {k_eq}:\n{case_a}{pad}case {k_ne}:\n{case_b}'
        else:
            cases = f'{pad}case {k_ne}:\n{case_b}{pad}default:\n{pad}case {k_eq}:\n{case_a}'
        switch = f'{pad}switch ({variable}) {{\n{cases}{pad}}}\n'
        if nested:
            text = f'{indent}}} else {{\n{switch}{indent}}}\n'
        else:
            text = switch
        out.append(source[:head.start()] + text + source[end:])
    return out


def variants(source, name):
    result = []
    for head in _IF.finditer(source):
        for text in _rewrites(source, head):
            result.append((FAMILY, text))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
