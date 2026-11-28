"""Recover switches from compare trees with local computations before an early-return guard.

A controller dispatch's five guarded cases compiled closer after recovering the switch: 6261 to 4496.
Only discard a guard's prefix on the returning path when it assigns an ordinary scalar local from another
ordinary scalar local and a literal; those values cannot be observed after the return.
"""
import re

from .compare_tree_default_switch import _IF, _condition, _leaf_for, _own_break, _statement_if, _tree, _walk
from .csource import _blank, find

FAMILY = 'guarded_compare_switch'
IDENT = r'[A-Za-z_]\w*'
SCALAR = r'(?:s8|u8|s16|u16|s32|u32|int|unsigned|signed|short|char)'
PREFIX = re.compile(r'\s*(?:' + SCALAR + r'\s+(' + IDENT + r')\s*;\s*)?('
                    + IDENT + r')\s*=\s*(' + IDENT + r')\s*&\s*(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*\s*;\s*')
GUARD = re.compile(r'if\s*\(\s*(' + IDENT + r')\s*!=\s*(0[xX][0-9a-fA-F]+|\d+)\s*\)\s*\{\s*return\s*;\s*\}')


def _rewrite(source, clean, at, function):
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
    if len(tests) < 2:
        return None
    local_text = clean[function[0]:function[1]]
    guarded = {}
    for node in nodes:
        if node[0] != 'leaf':
            continue
        start, end = node[1]
        prefix = PREFIX.match(clean, start, end)
        guard = prefix and GUARD.match(clean, prefix.end(), end)
        if not guard or guard[1] != variable:
            continue
        declared, target, operand = prefix.groups()
        # Both names must be non-volatile, non-static scalar locals (or scalar parameters), with no alias.
        for name in (target, operand):
            declarations = re.findall(r'\b((?:(?:const|volatile|static|register)\s+)*' + SCALAR + r')\s+'
                                      + re.escape(name) + r'\b', local_text)
            if not declarations or any(re.search(r'\b(?:volatile|static)\b', d) for d in declarations):
                break
        else:
            if declared and declared != target:
                continue
            guarded[node[1]] = (int(guard[2], 0), prefix.end(), guard.end())
    if not guarded:
        return None

    def arm(value):
        leaf = _leaf_for(tree, value)
        guard = guarded.get(leaf)
        return ('return',) if guard and value != guard[0] else ('body', leaf)

    constants = sorted({k for node in tests for k in node[2]} | {g[0] for g in guarded.values()})
    probes = sorted({k + d for k in constants for d in (-1, 0, 1)} | {constants[0] - 100000, constants[-1] + 100000})
    default = arm(probes[0])
    if default != ('return',) or arm(probes[-1]) != default:
        return None
    cases = {}
    for value in probes[1:-1]:
        result = arm(value)
        if result != default:
            cases.setdefault(result[1], []).append(value)
    # Between adjacent bounds the decision tree is constant. A gap cannot be a finite switch case.
    for left, right in zip(probes, probes[1:]):
        if right - left > 1 and arm(left + 1) != default:
            return None
    if not cases or sum(map(len, cases.values())) > 24 or any(_own_break(clean, span) for span in cases):
        return None
    indent = re.search(r'[ \t]*$', source[:at])[0]
    blocks = {}
    for span in sorted(cases):
        lines = []
        for value in cases[span]:
            lines.append(f'{indent}case {value:#x}:\n')
        body = source[span[0]:span[1]]
        if span in guarded:
            _, prefix_end, guard_end = guarded[span]
            body = source[span[0]:prefix_end] + source[guard_end:span[1]]
        lines.append(f'{indent}    {{\n{body}\n{indent}    }}\n{indent}    break;\n')
        blocks[span] = ''.join(lines)
    order = sorted(cases)
    orders = [order, sorted(order, key=lambda span: min(cases[span]))]
    if len(order) <= 8:
        orders += [order[:i] + [order[-1]] + order[i:-1] for i in range(len(order) - 1)]
    return [source[:at] + f'switch ({variable}) {{\n' + ''.join(blocks[s] for s in choice)
            + f'{indent}default:\n{indent}    return;\n{indent}}}' + source[stop:] for choice in orders]


def variants(source, name):
    function = find(source, name)
    if not function:
        return []
    clean = _blank(source)
    out = []
    for found in _IF.finditer(clean, function[0], function[1]):
        if clean[:found.start()].rstrip().endswith('else'):
            continue
        children = _rewrite(source, clean, found.start(), function)
        if children:
            out.extend((FAMILY, child) for child in children if (FAMILY, child) not in out)
    return out


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
