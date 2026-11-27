"""m2c's compare tree whose default arm is reached by a `goto` into a sibling arm, written back as the `switch`.

GCC lays a `switch` out as a tree of compares, with the `default:` arm's code next to one of the leaves. m2c reads
that as nested `if`s with a `goto` from the other leaves that fall to the default:

    if (v != 2) {                                       switch (v) {
        if (v >= 3) {                          ->       case 3:  C
            if (v != 3) {                               ...
                if (v != 4) { goto other; }             case 4:  D
                D                                       case 2:  B
            } else { C }                                default: A
        } else { other: A }                             }
    } else { B }

A leaf may also hold the statements the `goto` leaf repeats before the label (`j = 0; goto body;` for
`j = 0; body: ...`), and a leaf may be empty (the values that do nothing). The values the tree sends to each leaf are
found by running its comparisons on every constant and its neighbours; the leaf the far values reach is `default:`.
Nothing is rewritten when a range of values (not single values) leads anywhere else, or when an arm has a `break` of
the loop around the tree.

A 257-instruction N64 record builder under KMC `-O1` went from 17360 with its tables typed to a chain that reached 0
only with this switch (2730 without it). A 158-instruction flag pass has the same tree with an empty case list.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'compare_tree_default_switch'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
_IF = re.compile(r'if\s*\(')
_CAST = re.compile(r'\(\s*(?:signed\s+|unsigned\s+)?(?:s8|u8|s16|u16|s32|u32|int|short|char)\s*\)')
_TERM = re.compile(r'\s*([+-]?)\s*(0[xX][0-9a-fA-F]+|\d+|[A-Za-z_]\w*)[uUlL]*')
_OPS = {'==': lambda a, b: a == b, '!=': lambda a, b: a != b, '<': lambda a, b: a < b,
        '>': lambda a, b: a > b, '<=': lambda a, b: a <= b, '>=': lambda a, b: a >= b}


def _sum(text):
    """[(sign, term)] of a sum such as `v + 1` or `0x4000 - 1`, or None."""
    text = text.replace('(', ' ').replace(')', ' ').strip()
    at, out = 0, []
    while at < len(text):
        found = _TERM.match(text, at)
        if not found or (out and not found[1]):
            return None
        out.append((-1 if found[1] == '-' else 1, found[2]))
        at = found.end()
    return out or None


def _condition(text):
    """(variable, test(value) -> bool, constants) for a comparison of one variable with constants, or None."""
    text = _CAST.sub('', text)
    if re.search(r'-\s*\(|&&|\|\||\?', text):
        return None
    parts = re.split(r'(==|!=|<=|>=|(?<![<>])<(?![<=])|(?<![<>-])>(?![>=]))', text)
    if len(parts) != 3:
        return None
    left, right = _sum(parts[0]), _sum(parts[2])
    if left is None or right is None:
        return None
    names = {term for _, term in left + right if not term[0].isdigit()}
    if len(names) != 1 or any(not term[0].isdigit() for _, term in right):
        return None
    if [sign for sign, term in left if not term[0].isdigit()] != [1]:
        return None
    variable = names.pop()
    offset = sum(sign * int(term, 0) for sign, term in left if term[0].isdigit())
    bound = sum(sign * int(term, 0) for sign, term in right) - offset
    compare = _OPS[parts[1]]
    return variable, lambda value: compare(value, bound), (bound,)


def _statement_if(clean, at):
    """(condition span, then span, else span or None, end) of a braced `if` starting at `at`."""
    head = _IF.match(clean, at)
    if not head:
        return None
    cond_end = close(clean, head.end() - 1)
    brace = cond_end and re.compile(r'\s*\{').match(clean, cond_end)
    if not brace:
        return None
    then_end = close(clean, brace.end() - 1, '{', '}')
    if not then_end:
        return None
    other = re.compile(r'\s*else\s*\{').match(clean, then_end)
    if other:
        else_end = close(clean, other.end() - 1, '{', '}')
        if not else_end:
            return None
        return (head.end(), cond_end - 1), (brace.end(), then_end - 1), (other.end(), else_end - 1), else_end
    chained = re.compile(r'\s*else\s+(?=if\b)').match(clean, then_end)
    if chained:  # m2c writes `else if (..) {..}` without braces
        nested = _statement_if(clean, chained.end())
        if not nested:
            return None
        return (head.end(), cond_end - 1), (brace.end(), then_end - 1), (chained.end(), nested[3]), nested[3]
    if re.compile(r'\s*else\b').match(clean, then_end):
        return None
    return (head.end(), cond_end - 1), (brace.end(), then_end - 1), None, then_end


def _tree(clean, start, stop, variable):
    """The decision tree of clean[start:stop]: ('if', test, constants, then, other) or ('leaf', span)."""
    lead = len(clean[start:stop]) - len(clean[start:stop].lstrip())
    parsed = _statement_if(clean, start + lead)
    if parsed and not clean[parsed[3]:stop].strip():
        condition = _condition(clean[parsed[0][0]:parsed[0][1]])
        if condition and condition[0] == variable:
            then = _tree(clean, *parsed[1], variable)
            other = _tree(clean, *parsed[2], variable) if parsed[2] else ('leaf', (parsed[3], parsed[3]))
            return ('if', condition[1], condition[2], then, other)
    if parsed and not parsed[2] and re.match(r'\s*goto\s+' + IDENT + r'\s*;\s*$', clean[parsed[1][0]:parsed[1][1]]):
        condition = _condition(clean[parsed[0][0]:parsed[0][1]])
        if condition and condition[0] == variable:  # `if (c) { goto L; } rest`: the rest is the other branch
            return ('if', condition[1], condition[2], ('leaf', parsed[1]), ('leaf', (parsed[3], stop)))
    return ('leaf', (start, stop))


def _walk(node):
    if node[0] == 'leaf':
        yield node
        return
    yield node
    yield from _walk(node[3])
    yield from _walk(node[4])


def _leaf_for(node, value):
    while node[0] == 'if':
        node = node[3] if node[1](value) else node[4]
    return node[1]


def _own_break(clean, span):
    """Whether clean[span] has a `break` that is not inside a loop or switch of its own."""
    text = clean[span[0]:span[1]]
    for found in re.finditer(r'\b(for|while|switch|do)\b', text):
        opening = text.find('{', found.end())
        end = close(text, opening, '{', '}') if opening >= 0 else None
        if end:
            text = text[:opening] + ' ' * (end - opening) + text[end:]
    return re.search(r'\bbreak\b', text) is not None


def _squash(text):
    return re.sub(r'\s+', '', text)


def _resolve(source, clean, leaves):
    """{leaf span: (arm span it runs, label to drop)}, following one `goto` into another leaf."""
    labels = {}
    for span in leaves:
        for found in re.finditer(r'(?<![\w?])(' + IDENT + r')\s*:(?!:)', clean[span[0]:span[1]]):
            if found[1] not in ('default', 'case'):
                labels[found[1]] = (span, span[0] + found.start(), span[0] + found.end())
    out, used = {}, set()
    for span in leaves:
        jump = re.search(r'(?:^|(?<=[;{}\s]))goto\s+(' + IDENT + r')\s*;\s*$', clean[span[0]:span[1]])
        if jump and jump[1] in labels:
            target, begin, end = labels[jump[1]]
            before = _squash(source[span[0]:span[0] + jump.start()])
            if target == span or before != _squash(source[target[0]:begin]):
                return None
            out[span] = target
            used.add(jump[1])
        else:
            out[span] = span
    return out, {name: labels[name] for name in used}


def _body(source, span, labels, indent):
    text = source[span[0]:span[1]]
    for name, (target, begin, end) in labels.items():
        if target == span and len(re.findall(r'\bgoto\s+' + name + r'\b', source)) == 1:
            text = source[span[0]:begin] + source[end:span[1]]
    text = text.strip()
    return f'{indent}    {{\n{indent}        {text}\n{indent}    }}\n' if text else ''


def _rewrite(source, clean, at):
    parsed = _statement_if(clean, at)
    if not parsed:
        return None
    condition = _condition(clean[parsed[0][0]:parsed[0][1]])
    if not condition:
        return None
    variable, stop = condition[0], parsed[3]
    tree = _tree(clean, at, stop, variable)
    nodes = list(_walk(tree))
    tests = [node for node in nodes if node[0] == 'if']
    leaves = [node[1] for node in nodes if node[0] == 'leaf']
    if len(tests) < 3:
        return None
    resolved = _resolve(source, clean, leaves)
    if not resolved or not resolved[1]:
        return None
    runs, labels = resolved
    # every `goto` to these labels is one of the tree's leaves
    for name in labels:
        if len(re.findall(r'\bgoto\s+' + name + r'\b', clean)) != len(re.findall(r'\bgoto\s+' + name + r'\b',
                                                                              clean[at:stop])):
            return None

    def arm(value):
        span = runs[_leaf_for(tree, value)]
        return span if source[span[0]:span[1]].strip() else None

    constants = sorted({k for node in tests for k in node[2]})
    probes = sorted({k + d for k in constants for d in (-1, 0, 1)})
    far = arm(constants[-1] + 100000)
    if arm(constants[0] - 100000) != far and constants[0] > 1:
        return None
    cases = {}
    for value in probes:
        if value >= 0 and arm(value) != far:
            cases.setdefault(arm(value), []).append(value)
    for node in tests:  # a whole range leading away from the default is no list of cases
        for k in node[2]:
            for value in (k - 2, k + 2, (k + constants[-1]) // 2):
                if value >= 0 and arm(value) != far and value not in probes:
                    return None
    values = [v for group in cases.values() for v in group]
    if not values or len(values) > 24 or (len(values) > 2 and any(values.count(v) > 1 for v in values)):
        return None
    if any(span and _own_break(clean, span) for span in list(cases) + [far]):
        return None
    indent = re.search(r'[ \t]*$', source[:at])[0]
    order = sorted(cases, key=lambda span: span[0] if span else -1)

    def block(span):
        names = ''.join(f'{indent}case {v:#x}:\n' if v > 9 else f'{indent}case {v}:\n' for v in cases[span])
        return names + (_body(source, span, labels, indent) if span else '') + f'{indent}    break;\n'

    default = (f'{indent}default:\n' + _body(source, far, labels, indent) + f'{indent}    break;\n') if far else ''
    out = []
    for first in (False, True):
        if first and not default:
            continue
        arms = ''.join(block(span) for span in order)
        arms = default + arms if first else arms + default
        out.append(source[:at] + f'switch ({variable}) {{\n{arms}{indent}}}' + source[stop:])
    return out


def _sink(text, name):
    """The one store of a variable that ends every arm of a `switch`, written in each arm instead, or None.

    m2c collects the arms' results in a variable and stores it once after the switch; GCC merges the arms' identical
    stores into that one place itself, with other registers than a variable of its own gives (a record builder's last
    field: 1705 through the repairs with the variable, 0 with the store in each arm)."""
    clean = _blank(text)
    span = find(text, name)
    for switch in re.finditer(r'\bswitch\s*\(', clean[:span[1]]):
        opening = clean.find('{', switch.end())
        end = close(clean, opening, '{', '}') if opening >= 0 else None
        store = end and re.compile(r'\s*([^;{}=]+?)\s*=\s*(' + IDENT + r')\s*;').match(clean, end)
        if not store:
            continue
        target, local = text[store.start(1):store.end(1)], store[2]
        body = clean[opening:end]
        ends = list(re.finditer(r'(?<![\w.>])' + local + r'(\s*)=(?!=)([^;{}]*);(?=[\s}]*break\s*;)', body))
        if (not ends or 'default' not in body or len(ends) != len(re.findall(r'\bbreak\s*;', body))
                or len(re.findall(r'\b' + local + r'\b', body)) != len(ends)
                or len(re.findall(r'\b' + local + r'\b', clean[span[0]:span[1]])) != len(ends) + 2
                or re.search(r'\b' + local + r'\b', target)):
            continue
        arms = text[opening:end]
        for found in reversed(ends):
            arms = arms[:found.start()] + target + ' = ' + arms[found.start(2):found.end(2)].strip() + ';' + arms[found.end():]
        out = text[:opening] + arms + text[store.end():]
        return re.sub(r'\n[ \t]*(?:s8|u8|s16|u16|s32|u32|int|short|char)[ \t]+' + local + r'[ \t]*;', '', out)
    return None


def variants(source, name):
    span = find(source, name)
    if not span or 'goto' not in source:
        return []
    clean = _blank(source)
    out = []
    position = clean.find('{', span[0], span[1])
    spans = []
    for found in _IF.finditer(clean, max(position, 0), span[1]):
        if any(a <= found.start() < b for a, b in spans) or clean[:found.start()].rstrip().endswith('else'):
            continue
        rewritten = _rewrite(source, clean, found.start())
        if rewritten:
            spans.append((found.start(), _statement_if(clean, found.start())[3]))
            out.append((found.start(), rewritten))
    if not out:
        return []
    results = []
    for choice in range(2):
        text = source
        # every tree of the function at once, from the last so the earlier ones keep their places
        for _ in range(len(out)):
            now = _blank(text)
            for found in _IF.finditer(now, max(now.find('{', find(text, name)[0]), 0)):
                if now[:found.start()].rstrip().endswith('else'):
                    continue
                rewritten = _rewrite(text, now, found.start())
                if rewritten:
                    text = rewritten[min(choice, len(rewritten) - 1)]
                    break
        if text != source and (FAMILY, text) not in results:
            sunk = _sink(text, name)
            if sunk:
                results.append((FAMILY, sunk))
            results.append((FAMILY, text))
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
