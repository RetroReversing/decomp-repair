"""An `if` tree over one variable inside a function, read back as the `switch` it came from, ranges and `else if` included.

`if_tree_switch` reads a tree that is the whole rest of a function and tests single values; m2c's output for a small
`switch` is often only a statement among others (a screen layout chosen by a count, in the middle of a setup
function), it tests ranges (`>= 3`, `< 5`) beside single values, and its `else` is an `else if`:

    if (count != 2) {
        if (count >= 3) {
            if (count < 5) { w = 80.0f; h = 60.0f; }
        }
    } else
        if (flag == 1) { w = 80.0f; } else { h = 60.0f; }

gcc lays a `switch` out as a dispatch (`beq`, `slti`, `slti`) followed by the case bodies in the order of the cases, so
the single-value arm comes first and the grouped range second. Written as the nested `if`s the range arm comes first
and the code is a different size and order (a 1133-instruction effect spawner: the first region of its diff, 18
differing rows -> 1, with the cases `2` then `3`/`4` as `switch (count)`).

The tree is the one `if` statement (its `else` chain included) whose first test is `variable OP constant`; its meaning is
worked out for the value in each interval between the constants it tests (an `==`/`!=` splits at the constant and the
next value, `<`/`>=` at the constant, `<=`/`>` at the next value). Values that reach the same statements share a case;
the values on both ends of the line must run the same statements: that group is the default. A tree needs two tests
on the variable at least (one test is an `if`). Only trees whose arms
neither `return` nor jump, loop, or change the variable are read (the arms' own `if`s on other variables stay as written).
"""
import re

from .csource import _blank, find
from .if_tree_switch_repairs import TEST, Bail, _reindent, _walk
from .pattern_repairs import close

FAMILY = 'embedded_if_tree_switch'
FAMILIES = (FAMILY,)
LIMIT = 4
MAX_CASE_VALUES = 8

IDENT = r'[A-Za-z_]\w*'


def _block(source, clean, start, end):
    """The statements of source[start:end] (a block's inside) as ('if', cond, then, else, text) or ('plain', text)."""
    items, i = [], start
    while i < end:
        while i < end and clean[i] in ' \t\n':
            i += 1
        if i >= end:
            break
        if re.match(r'if\s*\(', clean[i:end]):
            item, i = _if(source, clean, i, end)
            items.append(item)
            continue
        if re.match(r'(?:for|while|do|switch|goto|case|default)\b|' + IDENT + r'\s*:(?!:)', clean[i:end]) \
                or clean[i] == '{':
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


def _if(source, clean, i, end):
    """One `if` statement at `i` (an `else if` chain included): (item, position after it)."""
    head = re.match(r'if\s*\(', clean[i:end])
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
    after = then_close
    if re.match(r'else\b', clean[j:end]):
        k = j + 4
        while k < end and clean[k] in ' \t\n':
            k += 1
        if clean[k:k + 1] == '{':
            else_close = close(clean, k, '{', '}')
            if not else_close:
                raise Bail
            other = _block(source, clean, k + 1, else_close - 1)
            after = else_close
        elif re.match(r'if\s*\(', clean[k:end]):
            nested, after = _if(source, clean, k, end)
            other = [nested]
        else:
            raise Bail
    return ('if', clean[cond_open + 1:cond_close - 1], _block(source, clean, then_open + 1, then_close - 1), other,
            source[i:after].strip()), after


def _boundaries(items, var, found, tests):
    """The values where a test on `var` may change its answer (the first value of each interval)."""
    for item in items:
        if item[0] != 'if':
            if re.search(r'\b' + re.escape(var) + r'\b\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', item[1]):
                raise Bail  # the tested variable changes inside the tree
            continue
        test = TEST.match(item[1])
        if test and test[1] == var:
            tests.append(item[1])
            constant = int(test[3].replace(' ', ''), 0)
            if test[2] in ('==', '!='):
                found.update((constant, constant + 1))
            elif test[2] in ('<', '>='):
                found.add(constant)
            else:
                found.add(constant + 1)
        _boundaries(item[2], var, found, tests)
        _boundaries(item[3] or [], var, found, tests)


def _tree_switch(source, clean, start):
    """(end of the tree statement, the variable, [(first value, last value, statements)], default statements)."""
    try:
        item, end = _if(source, clean, start, len(clean))
    except Bail:
        return None
    test = TEST.match(item[1])
    if not test:
        return None
    var = test[1]
    try:
        found, tests = set(), []
        _boundaries([item], var, found, tests)
        if len(tests) < 2:
            return None  # one test is an `if`/`else`, not a switch
        # one value for each interval: before the first boundary, from each boundary to the next, from the last on
        starts = [min(found) - 1] + sorted(found)
        paths = []
        for value in starts:
            out = []
            if _walk([item], value, var, out):
                return None  # a `return` in the tree: that is the old family's
            paths.append(tuple(out))
    except Bail:
        return None
    default = paths[0]
    if paths[-1] != default:
        return None
    intervals = []
    for index, value in enumerate(starts):
        if paths[index] == default:
            continue
        last = starts[index + 1] - 1
        if last - value + 1 > MAX_CASE_VALUES:
            return None
        intervals.append((value, last, paths[index]))
    if not intervals:
        return None
    return end, var, intervals, default


def _arm(statements, inner):
    return ''.join(inner + '    ' + _reindent(s, inner + '    ') + '\n' for s in statements) + inner + '    break;\n'


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
    covered = 0
    for hit in re.finditer(r'\bif\s*\(', clean[opening:end]):
        start = opening + hit.start()
        if start < covered:
            continue  # inside a tree already rewritten
        before = clean[opening + 1:start].rstrip()
        if not before or before[-1] not in ';{}':
            continue  # the `if` of an `else if`, or inside an expression
        found = _tree_switch(source, clean, start)
        if not found:
            continue
        stop, var, intervals, default = found
        covered = stop
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:start])[0]
        inner = indent + '    '

        for order in (intervals, list(reversed(intervals))):
            groups = []
            for first, last, path in order:
                for group in groups:
                    if group[0] == path:
                        group[1].append((first, last))
                        break
                else:
                    groups.append((path, [(first, last)]))
            text = 'switch (' + var + ') {\n'
            for path, ranges in groups:
                for first, last in ranges:
                    for value in range(first, last + 1):
                        text += inner + f'case {hex(value) if abs(value) > 9 else value}:\n'
                text += _arm(path, inner)
            if default:
                text += inner + 'default:\n' + _arm(default, inner)
            text += indent + '}'
            out = source[:start] + text + source[stop:]
            if all(out != other for _, other in result):
                result.append((FAMILY, out))
        if len(result) >= LIMIT:
            break
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
