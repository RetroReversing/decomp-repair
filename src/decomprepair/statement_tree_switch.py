"""A comparison tree over one variable in the middle of a function, with range tests, written as the `switch` it came from.

`if_tree_switch` reads the tree that ends a function (every leaf returns) and only constants the tree tests itself.
A panel builder's two trees were not that: each sat in a loop body among other statements, its leaves set a few values
and fell through, and its middle leaf covered a range (`!= 2`, `>= 2`, `< 5`, so `3` and `4` share an arm). The target's
compare chain (`beq 2`, `slti 2`, `slti 5`) is what a `switch` with `case 2:` and `case 3: case 4:` compiles to, and
the nested `if`s do not make it: 13755 for the first tree and 13464 for the second, 14200 before them (the second also
wanted its `default:` written first, 13464 -> 12296: the arms' code is laid out in the order the labels were written).

`variants` reads each `if` statement whose condition compares an identifier with a constant (either side), walks the
tree for every integer between its smallest and largest constant (at most 32 of them) and one value outside each end,
and writes a `switch (VAR)` when both outsides run the same statements (the default). Arms with the same statements
share their labels; a leaf's own `if` on another variable is part of the arm; a tree with a `return`, `goto`, loop,
label, `break` or `continue`, or one that assigns the variable, is left alone. The `default:` goes last and, when it
has statements, first as another child; the arms in ascending order. At most four children."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'statement_tree_switch'
FAMILIES = (FAMILY,)
LIMIT = 4
SPAN = 32
IDENT = r'[A-Za-z_]\w*'
NUMBER = r'-?\s*(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
FORWARD = re.compile(rf'^\s*\(?\s*({IDENT})\s*(==|!=|<=|>=|<|>)\s*({NUMBER})\s*\)?\s*$')
BACKWARD = re.compile(rf'^\s*\(?\s*({NUMBER})\s*(==|!=|<=|>=|<|>)\s*({IDENT})\s*\)?\s*$')
FLIP = {'==': '==', '!=': '!=', '<': '>', '<=': '>=', '>': '<', '>=': '<='}
OPS = {'==': lambda a, b: a == b, '!=': lambda a, b: a != b, '<': lambda a, b: a < b, '<=': lambda a, b: a <= b,
       '>': lambda a, b: a > b, '>=': lambda a, b: a >= b}


class Bail(Exception):
    pass


def _number(text):
    return int(re.sub(r'[uUlL]+$', '', text.replace(' ', '')), 0)


def _test(cond):
    """(variable, operator, constant) of `v OP K` or `K OP v`, else None."""
    hit = FORWARD.match(cond)
    if hit:
        return hit[1], hit[2], _number(hit[3])
    hit = BACKWARD.match(cond)
    if hit:
        return hit[3], FLIP[hit[2]], _number(hit[1])
    return None


def _python_split(cond, token):
    """`cond` cut at the top-level `token` (`||` or `&&`)."""
    parts, depth, last, at = [], 0, 0, 0
    while at < len(cond):
        char = cond[at]
        depth += (char == '(') - (char == ')')
        if depth == 0 and cond.startswith(token, at):
            parts.append(cond[last:at])
            last = at = at + len(token)
            continue
        at += 1
    parts.append(cond[last:])
    return parts


_split = _python_split
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _split(cond, token):
        found = _scan.split_top(cond, token, False)
        return _python_split(cond, token) if found is NotImplemented else found


def _atoms(cond):
    """The (variable, operator, constant) tests of a condition made of `||`, `&&` and parentheses, else None."""
    cond = cond.strip()
    while cond.startswith('(') and cond.endswith(')') and len(_split(cond[1:-1], '||')) * len(_split(cond[1:-1], '&&')) >= 1 \
            and cond[1:-1].count('(') == cond[1:-1].count(')'):
        cond = cond[1:-1].strip()
    out = []
    for or_part in _split(cond, '||'):
        for and_part in _split(or_part, '&&'):
            and_part = and_part.strip()
            if and_part.startswith('(') and and_part.endswith(')') and (len(_split(and_part[1:-1], '||')) > 1
                                                                        or len(_split(and_part[1:-1], '&&')) > 1):
                inner = _atoms(and_part)
                if inner is None:
                    return None
                out += inner
                continue
            test = _test(and_part)
            if not test:
                return None
            out.append(test)
    return out


def _holds(cond, value):
    """True or False for the condition at `value`, None when it tests more than one variable or something else."""
    cond = cond.strip()
    if cond.startswith('(') and cond.endswith(')') and cond[1:-1].count('(') == cond[1:-1].count(')'):
        return _holds(cond[1:-1], value)
    parts = _split(cond, '||')
    if len(parts) > 1:
        results = [_holds(part, value) for part in parts]
        return None if None in results else any(results)
    parts = _split(cond, '&&')
    if len(parts) > 1:
        results = [_holds(part, value) for part in parts]
        return None if None in results else all(results)
    test = _test(cond)
    return OPS[test[1]](value, test[2]) if test else None


def _skip(clean, at, end):
    while at < end and clean[at] in ' \t\n':
        at += 1
    return at


def _statement_end(clean, at, end):
    """End of the `if` statement (its `else` blocks included) that starts at `at`, or None."""
    head = re.match(r'if\s*\(', clean[at:end])
    if not head:
        return None
    cond_close = close(clean, at + head.end() - 1)
    if not cond_close:
        return None
    then_open = clean.find('{', cond_close)
    if then_open < 0 or clean[cond_close:then_open].strip():
        return None
    stop = close(clean, then_open, '{', '}')
    if not stop:
        return None
    after = _skip(clean, stop, end)
    if re.match(r'else\b', clean[after:end]):
        k = _skip(clean, after + 4, end)
        if clean[k:k + 1] == '{':
            return close(clean, k, '{', '}')
        return _statement_end(clean, k, end)  # `else if`: the `if` is the whole else; `else stmt` is not read
    return stop


def _statements(source, clean, start, end):
    """The statements of source[start:end] as ('if', cond, then, else, text) or ('plain', text) items."""
    items, i = [], start
    while i < end:
        i = _skip(clean, i, end)
        if i >= end:
            break
        if re.match(r'if\s*\(', clean[i:end]):
            stop = _statement_end(clean, i, end)
            if not stop:
                raise Bail
            cond_open = clean.find('(', i)
            cond_close = close(clean, cond_open)
            then_open = clean.find('{', cond_close)
            then_close = close(clean, then_open, '{', '}')
            other = None
            if stop != then_close:
                else_at = _skip(clean, _skip(clean, then_close, end) + 4, end)
                if clean[else_at] == '{':
                    other = _statements(source, clean, else_at + 1, stop - 1)
                else:
                    other = _statements(source, clean, else_at, stop)
            items.append(('if', clean[cond_open + 1:cond_close - 1],
                          _statements(source, clean, then_open + 1, then_close - 1), other, source[i:stop].strip()))
            i = stop
            continue
        if re.match(r'(?:for|while|do|switch|goto|case|default|break|continue|return)\b|' + IDENT + r'\s*:(?!:)', clean[i:end]) \
                or clean[i] == '{':
            raise Bail
        stop, depth = i, 0
        while stop < end:
            char = clean[stop]
            depth += (char in '([') - (char in ')]')
            if char in '{}':
                raise Bail
            if char == ';' and depth == 0:
                break
            stop += 1
        if stop >= end:
            raise Bail
        items.append(('plain', source[i:stop + 1].strip()))
        i = stop + 1
    return items


def _changes(var, text):
    return re.search(rf'(?<![\w.]){re.escape(var)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(var)}\b|\b{re.escape(var)}\s*(?:\+\+|--)', text)


def _constants(items, var, found):
    for item in items:
        if item[0] == 'if':
            atoms = _atoms(item[1])
            if not atoms or {atom[0] for atom in atoms} != {var}:
                if re.search(rf'(?<![\w.]){re.escape(var)}\b', item[4]):
                    raise Bail  # the variable is part of a leaf's own condition or code
                continue
            found.update(atom[2] for atom in atoms)
            _constants(item[2], var, found)
            _constants(item[3] or [], var, found)
        elif _changes(var, item[1]):
            raise Bail  # the tested variable changes inside the tree


def _walk(items, value, var, out):
    for item in items:
        if item[0] == 'plain':
            out.append(item[1])
            continue
        atoms = _atoms(item[1])
        if not atoms or {atom[0] for atom in atoms} != {var}:
            out.append(item[4])
            continue
        _walk(item[2] if _holds(item[1], value) else (item[3] or []), value, var, out)


def _reindent(text, indent):
    lines = text.split('\n')
    if len(lines) == 1:
        return text
    base = min((len(line) - len(line.lstrip()) for line in lines[1:] if line.strip()), default=0)
    return lines[0] + ''.join('\n' + indent + line[base:] if line.strip() else '\n' for line in lines[1:])


def _switch(source, clean, start, stop):
    """[(text of the switch, default first)] for the `if` statement source[start:stop], or []."""
    try:
        items = _statements(source, clean, start, stop)
        if len(items) != 1 or items[0][0] != 'if':
            return []
        atoms = _atoms(items[0][1])
        if not atoms or len({atom[0] for atom in atoms}) != 1:
            return []
        var = atoms[0][0]
        constants = set()
        _constants(items, var, constants)
        if len(constants) < 2 or max(constants) - min(constants) > SPAN:
            return []
        paths = {}
        for value in range(min(constants) - 1, max(constants) + 2):
            out = []
            _walk(items, value, var, out)
            paths[value] = tuple(out)
    except Bail:
        return []
    low, high = min(paths), max(paths)
    if paths[low] != paths[high]:
        return []  # the two ends run different code: a range test the switch cannot say
    default = paths[low]
    cases = [value for value in sorted(paths) if value not in (low, high) and paths[value] != default]
    if not cases:
        return []
    indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:start])[0]
    inner = indent + '    '

    def arm(statements):
        return ''.join(inner + '    ' + _reindent(s, inner + '    ') + '\n' for s in statements) + inner + '    break;\n'

    groups = []
    for value in cases:
        for group in groups:
            if paths[group[0]] == paths[value]:
                group.append(value)
                break
        else:
            groups.append([value])
    labels = ''.join(''.join(inner + f'case {hex(v) if abs(v) > 9 else v}:\n' for v in group) + arm(paths[group[0]])
                     for group in groups)
    tail = inner + 'default:\n' + arm(default) if default else ''
    head = indent + f'switch ({var}) {{\n'
    out = [(head + labels + tail + indent + '}', False)]
    if default:
        out.append((head + tail + labels + indent + '}', True))
    return out


def variants(source, name):
    """Proposals: each comparison tree over one variable, written as a `switch` (default last, and first)."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    result, covered = [], 0
    for hit in re.finditer(r'(?m)^[ \t]*(if\s*\()', clean[opening:span[1]]):
        start = opening + hit.start(1)
        if start < covered:
            continue  # inside a tree already read
        stop = _statement_end(clean, start, span[1])
        if not stop:
            continue
        for text, _ in _switch(source, clean, start, stop):
            lead = source[source.rfind('\n', 0, start) + 1:start]
            result.append((FAMILY, source[:start - len(lead)] + text + source[stop:]))
        if result:
            covered = stop
    return [(family, text) for family, text in dict.fromkeys(result)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 63}
