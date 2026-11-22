"""Try short-circuit spelling for two proven boolean locals in a guard."""

import re

from .csource import _blank
from .frame_padding_repairs import declaration_ends
from .integer_repair_support import IDENT, edit, locals_for, refs, view
from .pattern_repairs import close
from .pointer_pair_repairs import qualified_types

FAMILY = 'boolean_guard_operands'
_GUARD = re.compile(rf'&&\s*\(\s*({IDENT})\s*(&)(?!&)\s*\(\s*({IDENT})\s*!=\s*NULL\s*\)\s*\)')
_NONZERO = re.compile(r'sltu (\$\w+), \$zero, (\$\w+)')


def _witness(rows):
    for index, (_, target, candidate) in enumerate(rows[:-1]):
        comparison = _NONZERO.fullmatch(target)
        if not comparison or not candidate.startswith(f'beqz {comparison[2]}, '):
            continue
        _, left, right = rows[index + 1]
        if (left.startswith('and ') and comparison[1] in left.split(', ')[1:]
                and right.startswith('andi ') and right.endswith(', 1')):
            return True
    return False


def _sink_witness(rows):
    for index, (_, target, candidate) in enumerate(rows[:-2]):
        comparison = _NONZERO.fullmatch(target)
        if not comparison or candidate != 'nop':
            continue
        if target not in [row[1] for row in rows[max(0, index - 8):index]]:
            continue
        second = _NONZERO.fullmatch(rows[index + 1][1])
        if (second and rows[index + 2][1].startswith('and ')
                and rows[index + 2][1].split(', ')[1:] == [comparison[1], second[1]]):
            return True
    return False


def _groups(part, opening, position):
    stack = []
    for token in re.finditer(r'[()]', part.clean[opening:position]):
        if token[0] == '(':
            stack.append(opening + token.start())
        else:
            stack.pop()
    return stack


def _sink(source, part, scalars, pointers, macros):
    # m2c wraps the comparison in its own parentheses: `(flag && (other != NULL))`.
    tail_test = re.compile(rf'&&\s*\(\s*({IDENT})\s*&&\s*(?:\(\s*({IDENT})\s*!=\s*NULL\s*\)|({IDENT})\s*!=\s*NULL)\s*\)')
    guards = []
    for hit in re.finditer(r'\bif\s*\(', part.body):
        opening = part.opening + hit.end()
        end = close(part.clean, opening)
        if end:
            guards.append((opening, end))
    for tail in tail_test.finditer(part.clean, part.opening + 1, part.end):
        flag, bare, plain = tail.groups()
        other = bare or plain
        if flag not in scalars or other not in pointers:
            continue
        uses = refs(part, scalars[flag])
        if len(uses) != 3 or uses[-1].start() != tail.start(1):
            continue
        assign = rf'{flag}\s*=\s*({IDENT})\s*!=\s*NULL\s*,\s*'
        sites = [re.match(assign, part.clean[ref.start():]) for ref in uses[:-1]]
        if not all(sites) or sites[0][1] != sites[1][1]:
            continue
        pointer = sites[0][1]
        names = {flag, pointer, other}
        if pointer not in pointers or len(names) != 3 or any(names & set(re.findall(IDENT, m)) for m in macros):
            continue
        if not _unique_names(part, names) or re.search(rf'(?:\+\+|--|(?<!&)\&(?!&))\s*\(*\s*{pointer}\b', part.body):
            continue
        writes = list(re.finditer(rf'(?<![.>\w]){pointer}\s*(?:=(?!=)|(?:<<|>>|[+\-*/%&|^])=|\+\+|--)', part.body))
        if len(writes) != 1:
            continue
        enclosing = next((start for start, end in guards if start < uses[0].start() < tail.end() < end), None)
        if enclosing is None or part.opening + 1 + writes[0].end() >= enclosing:
            continue
        groups = [_groups(part, enclosing, ref.start()) for ref in uses[:-1]]
        if any(len(stack) < 2 for stack in groups) or groups[0][-1] == groups[1][-1]:
            continue
        if not all(part.clean[enclosing:stack[-1]].rstrip().endswith(('(', '&&', '||')) for stack in groups):
            continue
        edits = [(ref.start(), ref.start() + site.end(), '') for ref, site in zip(uses, sites)]
        if any(source[a:b] != part.clean[a:b] for a, b, _ in edits):
            continue
        return [(FAMILY, edit(source, edits + [(tail.start(1), tail.end(1), pointer + ' != NULL')]))]
    return []


def _unique_names(part, names):
    return all(len(re.findall(rf'\b{IDENT}(?:\s+\**\s*|\s*\*+\s*){re.escape(var)}\s*(?=[;=,\[])',
                              part.body)) == 1 for var in names)


def variants(source, name, rows, header=''):
    splice, sink = _witness(rows), _sink_witness(rows)
    if not splice and not sink:
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm|__asm__)\b', part.body):
        return []
    context = _blank(header) + '\n' + part.clean
    scalars = {d['name']: d for d in locals_for(part) if d['type'] not in qualified_types(context)}
    pointers = set()
    begin = part.opening + 1
    for end in declaration_ends(part):
        declaration = re.fullmatch(rf'\s*void\s*\*\s*({IDENT})\s*;', part.clean[begin:end])
        if declaration:
            pointers.add(declaration[1])
        begin = end
    macros = re.findall(r'(?m)^[ \t]*#\s*(?:define|undef)\s+([^\n]+)', context.replace('\\\n', ' '))
    if any(re.match(r'NULL\b', macro) and not re.fullmatch(
            r'NULL\s+(?:0|\(0\)|\(\s*\(\s*void\s*\*\s*\)\s*0\s*\))\s*', macro) for macro in macros):
        return []
    out = _sink(source, part, scalars, pointers, macros) if sink else []
    if not splice:
        return out
    for hit in _GUARD.finditer(part.clean, part.opening + 1, part.end):
        flag, operator, ptr = hit.groups()
        if flag not in scalars or ptr not in pointers:
            continue
        if not _unique_names(part, (flag, ptr)) or any(set(re.findall(IDENT, macro)) & {flag, ptr} for macro in macros):
            continue
        others = [ref for ref in refs(part, scalars[flag]) if ref.start() != hit.start(1)]
        if not others or any(not re.match(
                rf'\s*=\s*({IDENT})\s*(?:!=|==)\s*NULL\s*[,;)]', part.clean[ref.end():])
                for ref in others):
            continue
        if any(re.search(r'(?:\+\+|--|(?<!&)\&(?!&))\s*\(*\s*$', part.clean[:ref.start()])
               for ref in others):
            continue
        if source[hit.start(2):hit.end(2)] == operator:
            out.append((FAMILY, edit(source, [(hit.start(2), hit.end(2), '&&')])))
    return out[:4]
