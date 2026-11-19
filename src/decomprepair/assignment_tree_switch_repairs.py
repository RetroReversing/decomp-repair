"""m2c's compare tree for a `switch` whose cases set values, written back as the `switch`.

gcc builds a `switch` of a few cases as a tree of compares; when the cases assign constants and fall into common code,
m2c reads them back as nested `if`s that share the assignments common to several paths:

    if (t != 0) {
        r = 0x40;
        if (t != 1) { r = 0xFF; g = 0xFF; } else { g = 0x40; }
        b = 0xFF;
    } else {
        r = 0xFF; g = 0x40; b = 0x40;
    }

An N64 function was 94.8% so, 83.9% as `if`/`else if`, and exact as `switch (t) { case 0: ... break; case 1: ...
break; default: ... break; }` with each case's final values in the order the variables are first assigned. Every block
may hold only constant assignments and further such `if`s on the same variable; each leaf is a case when its path fixes
the value with `==`, else the default. compare_tree_switch handles the trees whose leaves return.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'assignment_tree_switch'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'-?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
COMPARE = re.compile(r'\s*(?P<x>' + IDENT + r')\s*(?P<op>==|!=)\s*(?P<k>' + NUMBER + r')\s*$')
ASSIGN = re.compile(r'\s*(?P<v>' + IDENT + r')\s*=(?!=)\s*(?P<k>' + NUMBER + r')\s*;')


class _NotATree(Exception):
    pass


def _block(source, clean, start, stop, var, path, assigned, leaves):
    """Walk clean[start:stop] (a block's inside): constant assignments and `if`s on `var`; record each leaf."""
    at = start
    assigned = dict(assigned)
    while True:
        rest = clean[at:stop]
        if not rest.strip():
            leaves.append((path, assigned))
            return
        lead = len(rest) - len(rest.lstrip())
        at += lead
        m = ASSIGN.match(clean, at)
        if m and m.end() <= stop:
            assigned.pop(m['v'], None)
            assigned[m['v']] = source[m.start('k'):m.end('k')]
            at = m.end()
            continue
        if not re.match(r'if\s*\(', clean[at:stop]):
            raise _NotATree
        cond_open = clean.index('(', at)
        cond_close = close(clean, cond_open)
        test = COMPARE.match(clean[cond_open + 1:cond_close - 1])
        if not test or test['x'] != var:
            raise _NotATree
        then_open = cond_close + len(clean[cond_close:]) - len(clean[cond_close:].lstrip())
        if clean[then_open:then_open + 1] != '{':
            raise _NotATree
        then_close = close(clean, then_open, '{', '}')
        after = then_close + len(clean[then_close:stop]) - len(clean[then_close:stop].lstrip())
        has_else = re.match(r'else\s*\{', clean[after:stop])
        else_open = clean.index('{', after) if has_else else None
        else_close = close(clean, else_open, '{', '}') if has_else else None
        tail = (else_close if has_else else then_close)
        if clean[tail:stop].strip():
            # statements after the `if` are common to both arms: walk each arm, then the tail, per path
            arms = [(then_open, then_close, True)] + ([(else_open, else_close, False)] if has_else else [(None, None, False)])
            for a, b, taken in arms:
                sub = []
                fact = (test['op'] == '==') == taken
                if a is None:
                    sub.append((path + [(fact, source[cond_open + 1:cond_close - 1].strip(), test['k'])], dict(assigned)))
                else:
                    _block(source, clean, a + 1, b - 1, var,
                           path + [(fact, source[cond_open + 1:cond_close - 1].strip(), test['k'])], assigned, sub)
                for p, values in sub:
                    _block(source, clean, tail, stop, var, p, values, leaves)
            return
        for a, b, taken in [(then_open, then_close, True)] + ([(else_open, else_close, False)] if has_else else []):
            fact = (test['op'] == '==') == taken
            _block(source, clean, a + 1, b - 1, var,
                   path + [(fact, source[cond_open + 1:cond_close - 1].strip(), test['k'])], assigned, leaves)
        if not has_else:
            leaves.append((path + [((test['op'] == '==') is False, '', test['k'])], dict(assigned)))
        return


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
    for hit in re.finditer(r'(?m)^(?P<indent>[ \t]*)if\s*\(', clean[:end]):
        if hit.start() < opening:
            continue
        cond_open = clean.index('(', hit.start())
        cond_close = close(clean, cond_open)
        test = COMPARE.match(clean[cond_open + 1:cond_close - 1]) if cond_close else None
        if not test:
            continue
        then_open = clean.find('{', cond_close)
        then_close = close(clean, then_open, '{', '}')
        after = then_close + len(clean[then_close:]) - len(clean[then_close:].lstrip())
        if not re.match(r'else\s*\{', clean[after:end]):
            continue
        else_open = clean.index('{', after)
        else_close = close(clean, else_open, '{', '}')
        leaves = []
        try:
            _block(source, clean, hit.start('indent') + len(hit['indent']), else_close, test['x'], [], {}, leaves)
        except (_NotATree, ValueError, TypeError):
            continue
        cases, default, order = {}, None, []
        for path, values in leaves:
            for v in values:
                if v not in order:
                    order.append(v)
            equal = [int(k.rstrip('uUlL'), 0) for fact, _, k in path if fact]
            if equal:
                cases.setdefault(equal[-1], values)
            elif default is None:
                default = values
            elif default != values:
                break
        else:
            if not cases or default is None or len(cases) < 2:
                continue
            indent = hit['indent']

            def body(values, indent=indent, order=order):
                return ''.join(f'{indent}    {v} = {values[v]};\n' for v in order if v in values) + f'{indent}    break;\n'
            for keys in (sorted(cases), list(reversed(sorted(cases)))):
                text = (f'{indent}switch ({test["x"]}) {{\n'
                        + ''.join(f'{indent}case {k}:\n{body(cases[k])}' for k in keys)
                        + f'{indent}default:\n{body(default)}{indent}}}\n')
                line_end = clean.find('\n', else_close)
                candidate = source[:hit.start()] + text + source[line_end + 1:]
                if candidate not in [t for _, t in result]:
                    result.append((FAMILY, candidate))
    return result[:2]
