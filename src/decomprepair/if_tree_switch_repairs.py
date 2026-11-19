"""m2c's nested `if` tree over one variable, written as the `switch` it came from.

gcc lowers a small `switch` to a tree of comparisons, and m2c reads the tree back as nested `if`s that test one value
against constants (`!=`, `==`, `<`, `>=`, ...), with each case's code at a leaf:

    temp_a0 = arg0 & 0xFFFF;
    if (temp_a0 != 0x2000) {
        if (temp_a0 >= 0x2001) {
            if (temp_a0 != 0x8000) { return 1; }
            X = 0; return 1;
        }
        if (temp_a0 != 0) { return 1; }
        f(); return 0x2001;
    }
    g(); return 0x8001;

Written as C the tree compiles to different code; as `switch (arg0 & 0xFFFF) { case 0: ...; case 0x2000: ...;
case 0x8000: ...; } return 1;` an N64 function was exact (76.4% before). The tree's meaning is worked out by walking it
for each value that matters (every constant it tests, and one value in each range between them): the values that
reach the same statements share a case, and the one group that every range falls into is the default. Only `if`
trees without `goto`, labels, loops or `else if` chains on other values are read; anything else is left alone.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'if_tree_switch'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = re.compile(r'^\s*(-?\s*(?:0[xX][0-9a-fA-F]+|\d+))[uUlL]*\s*$')
TEST = re.compile(r'^\s*(' + IDENT + r')\s*(==|!=|<=|>=|<|>)\s*(-?\s*(?:0[xX][0-9a-fA-F]+|\d+))[uUlL]*\s*$')
OPS = {'==': lambda a, b: a == b, '!=': lambda a, b: a != b, '<': lambda a, b: a < b, '<=': lambda a, b: a <= b,
       '>': lambda a, b: a > b, '>=': lambda a, b: a >= b}


class Bail(Exception):
    pass


def _statements(source, clean, start, end):
    """The top-level statements of source[start:end] as ('if', cond, then, else) or ('plain', text) items."""
    items, i = [], start
    while i < end:
        while i < end and clean[i] in ' \t\n':
            i += 1
        if i >= end:
            break
        head = re.match(r'if\s*\(', clean[i:end])
        if head:
            cond_open = i + head.end() - 1
            cond_close = close(clean, cond_open)
            if not cond_close:
                raise Bail
            then_open = clean.find('{', cond_close)
            if then_open < 0 or clean[cond_close:then_open].strip():
                raise Bail
            then_close = close(clean, then_open, '{', '}')
            if not then_close:
                raise Bail
            j = then_close
            while j < end and clean[j] in ' \t\n':
                j += 1
            other = None
            if re.match(r'else\b', clean[j:end]):
                k = j + 4
                while k < end and clean[k] in ' \t\n':
                    k += 1
                if clean[k:k + 1] != '{':
                    raise Bail  # `else if` / `else stmt`: not read
                else_close = close(clean, k, '{', '}')
                if not else_close:
                    raise Bail
                other = _statements(source, clean, k + 1, else_close - 1)
                j = else_close
            items.append(('if', clean[cond_open + 1:cond_close - 1],
                          _statements(source, clean, then_open + 1, then_close - 1), other, source[i:j].strip()))
            i = j
            continue
        if re.match(r'(?:for|while|do|switch|goto|case|default)\b|' + IDENT + r'\s*:(?!:)', clean[i:end]) or clean[i] == '{':
            raise Bail
        stop = i
        depth = 0
        while stop < end:
            ch = clean[stop]
            depth += (ch in '([') - (ch in ')]')
            if ch in '{}':
                raise Bail
            if ch == ';' and depth == 0:
                break
            stop += 1
        if stop >= end:
            raise Bail
        items.append(('plain', source[i:stop + 1].strip()))
        i = stop + 1
    return items


def _walk(items, value, var, out):
    """The plain statements run for `value`; True when a `return` ended the walk."""
    for item in items:
        if item[0] == 'plain':
            out.append(item[1])
            if re.match(r'return\b', item[1]):
                return True
            continue
        test = TEST.match(item[1])
        if not test or test[1] != var:
            # an `if` on something else is part of a case's code, as it stands
            if re.search(r'\b' + re.escape(var) + r'\b', item[4]) or re.search(r'\breturn\b', item[4]):
                raise Bail
            out.append(item[4])
            continue
        branch = item[2] if OPS[test[2]](value, int(test[3].replace(' ', ''), 0)) else (item[3] or [])
        if _walk(branch, value, var, out):
            return True
    return False


def _constants(items, var, found):
    for item in items:
        if item[0] == 'if':
            test = TEST.match(item[1])
            if not test or test[1] != var:
                continue  # part of a case's code (_walk checks it doesn't touch the variable or return)
            found.add(int(test[3].replace(' ', ''), 0))
            _constants(item[2], var, found)
            _constants(item[3] or [], var, found)
        elif re.search(r'\b' + re.escape(var) + r'\b\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', item[1]):
            raise Bail  # the tested variable changes inside the tree


def _reindent(text, indent):
    lines = text.split('\n')
    if len(lines) == 1:
        return text
    base = min((len(line) - len(line.lstrip()) for line in lines[1:] if line.strip()), default=0)
    return lines[0] + ''.join('\n' + indent + line[base:] if line.strip() else '\n' for line in lines[1:])


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening + 1:end - 1]
    tree_at = re.search(r'(?m)^[ \t]*if\s*\(', body)
    if not tree_at:
        return []
    start = opening + 1 + tree_at.start()
    try:
        items = _statements(source, clean, start, end - 1)
    except Bail:
        return []
    if not items or items[0][0] != 'if':
        return []
    test = TEST.match(items[0][1])
    if not test:
        return []
    var = test[1]
    try:
        constants = set()
        _constants(items, var, constants)
        if not 2 <= len(constants) <= 8:
            return []
        points = sorted(constants)
        # one value in each range between (and outside) the tested constants
        ranges = [points[0] - 1, points[-1] + 1] + [a + 1 for a, b in zip(points, points[1:]) if b - a > 1]
        paths = {}
        for value in points + ranges:
            out = []
            ended = _walk(items, value, var, out)
            paths[value] = (tuple(out), ended)
    except Bail:
        return []
    defaults = {paths[v] for v in ranges}
    if len(defaults) != 1:
        return []  # the ranges behave differently: a range test, not a switch
    default = defaults.pop()
    cases = [v for v in points if paths[v] != default]
    if not cases:
        return []
    indent = re.match(r'[ \t]*', source[start:])[0]
    inner = indent + '    '

    def arm(path):
        statements, ended = path
        text = ''.join(inner + '    ' + _reindent(s, inner + '    ') + '\n' for s in statements)
        return text + ('' if ended else inner + '    break;\n')

    # the switched expression: the variable, or what it was set to when that's its only use
    switched = [var]
    assigned = list(re.finditer(r'(?m)^[ \t]*' + re.escape(var) + r'\s*=(?!=)\s*([^;]+);[ \t]*\n', clean[opening:start]))
    if len(assigned) == 1 and len(re.findall(r'\b' + re.escape(var) + r'\b', clean[opening:end])) - 1 == \
            len(re.findall(r'\b' + re.escape(var) + r'\b', clean[start:end])) + 1:
        switched.append(source[opening + assigned[0].start(1):opening + assigned[0].end(1)].strip())
    result = []
    for expr in switched:
        for order in (cases, list(reversed(cases))):
            groups = []
            for value in order:
                for group in groups:
                    if paths[group[0]] == paths[value]:
                        group.append(value)
                        break
                else:
                    groups.append([value])
            text = indent + 'switch (' + expr + ') {\n'
            for group in groups:
                text += ''.join(inner + f'case {hex(v) if abs(v) > 9 else v}:\n' for v in group) + arm(paths[group[0]])
            statements, ended = default
            text += indent + '}\n' + ''.join(indent + _reindent(s, indent) + '\n' for s in statements)
            out = source[:start] + text + source[end - 1:]
            if expr != var:
                decl = assigned[0]
                out = out[:opening + decl.start()] + out[opening + decl.end():]
                out = re.sub(r'(?m)^[ \t]*[\w ]+?\s+' + re.escape(var) + r'\s*;[ \t]*\n', '', out, count=1)
            if out not in [t for _, t in result]:
                result.append((FAMILY, out))
    return result[:4]
