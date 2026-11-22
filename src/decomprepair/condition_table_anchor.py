"""Order of a two-flag test table: put the first flag's operand first and keep the table's missing rows as empty tests.

A pair of small flags (the results of two calls, `s8 c1, c2`) tested as `if ((c1 != 0) & (c2 == 0))`,
`if ((c1 == 0) & (c2 != 0))` ... is a truth table. GCC 2.x numbers its pseudo registers in the order the source
expands them, and local-alloc hands out the caller-saved registers in that order (sign extensions, `sltiu`/`sltu`
results), so the order of operands and which rows of the table the author wrote decide which register each value
gets. The original's table is usually complete: a row whose body is empty is deleted by the optimizer but its
comparisons were numbered first (a function whose second two-flag block tested only two of the four rows matched
only once `if ((c1 == 0) & (c2 == 0)) { }` stood in front of them, with c1 named first in every test).

Proposals:
- condition_table_order: every test of one table written with the table's first flag first;
- condition_table_anchor: that, plus an empty test for each missing row (each one alone, then all of them), placed in
  front of the table's first test.

A table is two or more `if (...) {...}` tests in a row at one brace depth whose condition is
`(F op 0) & (G op 0)` over the same two locals (an `(unsigned)` cast on an operand is allowed), with no else."""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILIES = ('condition_table_order', 'condition_table_anchor')
LIMIT = 24
FLAG = rf'\(\s*(?:\(\s*unsigned\s*\)\s*)?\(?\s*(?P<{{v}}>{IDENT})\s*(?P<{{o}}>==|!=)\s*0\s*\)?\s*\)'
TEST = re.compile(r'\bif\s*\(\s*(?P<left>' + FLAG.format(v='a', o='p') + r')\s*&\s*(?P<right>' + FLAG.format(v='b', o='q') + r')\s*\)\s*{')


def tables(part):
    """Groups of back-to-back two-flag tests at one brace depth: lists of dicts (condition span, flags, operands)."""
    clean = part.clean
    tests = []
    for hit in TEST.finditer(clean, part.opening, part.end):
        end = close(clean, hit.end() - 1, '{', '}')
        if not end or re.match(r'\s*else\b', clean[end:]):
            continue
        tests.append({'start': hit.start(), 'brace': hit.end() - 1, 'end': end, 'vars': (hit['a'], hit['b']), 'ops': (hit['p'], hit['q']),
                      'left': hit['left'], 'right': hit['right'],
                      'depth': clean.count('{', part.opening, hit.start()) - clean.count('}', part.opening, hit.start())})
    groups, current = [], []
    for test in tests:
        if current and (test['depth'] == current[-1]['depth'] and clean[current[-1]['end']:test['start']].strip() == ''
                        and set(test['vars']) == set(current[-1]['vars'])):
            current.append(test)
            continue
        groups.append(current)
        current = [test]
    groups.append(current)
    return [g for g in groups if len(g) >= 2]


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return []
    out = []
    for group in tables(part):
        point = group[0]['start']
        line = source.rfind('\n', 0, point) + 1
        indent = source[line:point] if not source[line:point].strip() else ''
        # either flag may be the one named first: the table's first test says which the author wrote, not which the
        # compiler needed
        for first, second in (group[0]['vars'], group[0]['vars'][::-1]):
            reorder, rows = [], set()
            for test in group:
                if test['vars'][0] != first:
                    reorder.append((test['start'], test['brace'], f"if ({test['right']} & {test['left']}) "))
                rows.add(test['ops'] if test['vars'][0] == first else test['ops'][::-1])
            missing = [(p, q) for p in ('==', '!=') for q in ('==', '!=') if (p, q) not in rows]
            if reorder:
                out.append((FAMILIES[0], edit(source, reorder)))
            anchors = [f'if (({first} {p} 0) & ({second} {q} 0))\n{indent}{{\n{indent}}}\n{indent}' for p, q in missing]
            for chosen in [[one] for one in anchors] + ([anchors] if len(anchors) > 1 else []):
                out.append((FAMILIES[1], edit(source, [(point, point, ''.join(chosen))] + reorder)))
    return list(dict.fromkeys(out))[:LIMIT]
