"""Recover a small mode constant on the branches that actually use it."""

import re

from .goto_structure_repairs import statement
from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for
from .operand_lifetime_repairs import _escaped, _visible

FAMILY = 'rejected_branch_default'
_SETUP = re.compile(
    rf'(?m)^[ \t]*(?P<mode>var_s(?P<reg>[0-7])(?:_\d+)?)\s*'
    rf'=\s*(?P<value>{NUMBER})\s*;[ \t]*\n(?=[ \t]*if\s*\()'
)
_IMMEDIATE = re.compile(rf'addiu \$s([0-7]), \$zero, ({NUMBER})')
_PREDICATE = re.compile(rf'\s*!\s*\(\s*(?P<condition>{IDENT}\s*&\s*{IDENT})\s*\)\s*')
_ESCAPE = re.compile(r'\b(?:goto|return|break|continue|case|default)\b|(?m:^[ \t]*\w+\s*:)')


def _witnesses(rows):
    target = [(mark != ' ', op) for mark, op, _ in rows if op]
    first = {}
    exits = {}
    for i, ((_, branch), (different, slot)) in enumerate(zip(target, target[1:])):
        match = _IMMEDIATE.fullmatch(slot)
        if not match:
            continue
        key = (match[1], integer(match[2]))
        if branch.startswith('bc1f '):
            first[key] = i
        elif branch.startswith(('bnez ', 'bnel ')) and i - first.get(key, -100) <= 56:
            exits.setdefault(key, []).append((i, different))
    return {key for key, sites in exits.items()
            if any(3 <= j - i <= 24 and (changed or other)
                   for (i, changed), (j, other) in zip(sites, sites[1:]))}


def _statement_text(part, item):
    return part.clean[item.start:item.end]


def _shape(part, setup, mode, value):
    outer = statement(part.clean, setup.end(), part.end)
    if not outer or outer.kind != 'if':
        return None
    then, other = (outer.parts[key] for key in ('then', 'other'))
    if not other or not then['block'] or not other['block']:
        return None
    true_side = then['stmts']
    false_side = other['stmts']
    if not true_side or len(false_side) < 2:
        return None
    if not re.fullmatch(rf'{IDENT}\s*=(?!=)[^;]+;', _statement_text(part, true_side[0])):
        return None
    duplicate, branch = false_side[-2:]
    if _statement_text(part, duplicate) != f'{mode} = {value};' or branch.kind != 'if' or branch.parts['other']:
        return None
    start, end = branch.parts['cond']
    condition = _PREDICATE.fullmatch(part.clean[start:end])
    body = branch.parts['then']
    if not condition or not body['block']:
        return None
    following = next((item for item in body['stmts'] if _statement_text(part, item) == f'{mode} = {value};'), None)
    if not following:
        return None
    earlier = [
        part.clean[outer.start:then['open']], part.clean[then['open']:then['close']],
        part.clean[other['open']:duplicate.start], part.clean[branch.start:body['open']],
        part.clean[body['open']:following.start],
    ]
    if any(re.search(rf'\b{mode}\b', text) or _ESCAPE.search(text) for text in earlier):
        return None
    return true_side[0].end, duplicate.start, start, end, condition['condition']


def variants(source, name, rows, *, header=''):
    """Move the default to two exclusive arms when the remaining arm defines it."""
    witnesses = _witnesses(rows)
    visible = _visible(source, name, header) if witnesses else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\btypedef\b[^;\n]*\bvolatile\b[^;\n]*\bs32\s*;', context):
        return []
    scope = {m['name']: m['type'] for m in locals_for(part)}
    options = []
    for setup in _SETUP.finditer(part.clean, part.opening + 1, part.end):
        mode, value = setup['mode'], setup['value']
        if ((setup['reg'], integer(value)) not in witnesses or scope.get(mode) not in ('s32', 'int')
                or _escaped(part.body, mode)):
            continue
        if part.clean[part.opening + 1:setup.start()].rstrip()[-1:] not in (';', '{', '}', ':'):
            continue
        if not (match := _shape(part, setup, mode, value)):
            continue
        finish_first, duplicate, start, end, condition = match
        if re.search(r'/[*/]|#', source[setup.start():setup.end()] + source[duplicate:end]):
            continue
        names = '|'.join(re.findall(IDENT, condition) + [mode, 's32'])
        if re.search(rf'(?m)^\s*#\s*(?:define|undef)\s+(?:{names})\b', context):
            continue
        pad = source[source.rfind('\n', 0, duplicate) + 1:duplicate]
        true_pad = source[source.rfind('\n', 0, finish_first) + 1:finish_first]
        assignment = f'{mode} = {value};'
        replacement = f'if ({condition}) {{\n{pad}  {assignment}\n{pad}}}\n{pad}else'
        options.append(edit(source, [
            (setup.start(), setup.end(), ''),
            (finish_first, finish_first, '\n' + re.match(r'[ \t]*', true_pad)[0] + assignment),
            (duplicate, end + 1, replacement),
        ]))
    return [(FAMILY, options[0])] if len(options) == 1 else []
