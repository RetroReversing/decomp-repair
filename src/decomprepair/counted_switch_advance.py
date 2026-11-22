"""Place a witnessed byte threshold's reset before its advancing arm."""

import re

from .goto_structure_repairs import statement
from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for
from .operand_lifetime_repairs import _escaped, _visible

FAMILY = 'counted_switch_advance'
ADVANCE = 'repair_advance_state'
REG = r'\$\w+'
WORD = r'(?:0[xX][0-9a-fA-F]+|\d+)'
_READ = re.compile(rf'lbu ({REG}), ({WORD})\(({REG})\)')
_ADD = re.compile(rf'addiu ({REG}), ({REG}), ({WORD})')
_TEST = re.compile(rf'slti ({REG}), ({REG}), ({WORD})')
_STORE = re.compile(rf'sb ({REG}), ({WORD})\(({REG})\)')
_GUARD = re.compile(rf'\s*\(\s*\(\s*s8\s*\)\s*(?P<old>{IDENT})\s*\)\s*>=\s*(?P<bound>{NUMBER})\s*')
_LVALUE = re.compile(rf'\*\(\((?P<type>[us]8)\*\)\(\(\(char\*\)(?P<base>{IDENT})\)\+(?P<offset>{NUMBER})\)\)')
_ASSIGNMENT = re.compile(r'\s*(?P<lhs>[^=;]+?)\s*=\s*(?P<rhs>[^;]+?)\s*;\s*')
_ESCAPE = re.compile(r'\b(?:goto|break|continue|return|case|default)\b|(?m:^[ \t]*\w+\s*:)')


def _targets(rows):
    target = [(mark != ' ', op) for mark, op, _ in rows if op]
    old = [op for _, _, op in rows if op]
    reversed_exits = set()
    for i in range(len(old) - 5):
        read, compare = _READ.fullmatch(old[i]), _TEST.fullmatch(old[i + 4])
        if read and compare and compare[2] == read[1] and old[i + 5].startswith(f'beqz {compare[1]}, '):
            reversed_exits.add((integer(read[2]), integer(compare[3])))
    if not reversed_exits:
        return set()
    out = set()
    for i in range(len(target) - 9):
        window = target[i:i + 10]
        load, add, left, right, compare, branch, saved, reset, jump, fail = [line for _, line in window]
        read, inc, limit, store, constant, default = (
            _READ.fullmatch(load), _ADD.fullmatch(add), _TEST.fullmatch(compare),
            _STORE.fullmatch(saved), _ADD.fullmatch(reset), _STORE.fullmatch(fail),
        )
        if not all((read, inc, limit, store, constant, default)):
            continue
        byte, offset, base = read.groups()
        if inc[2] != byte or integer(inc[3]) != 1 or store.groups() != (inc[1], offset, base):
            continue
        if (limit[2] != byte or constant[2] != '$zero' or default[1] != constant[1] or default[3] != base
                or integer(default[2]) == integer(offset)):
            continue
        extension = rf'{re.escape(byte)}, {re.escape(byte)}, (?:24|0x18)'
        if not (re.fullmatch('sll ' + extension, left) and re.fullmatch('sra ' + extension, right)):
            continue
        if not (branch.startswith(f'bnez {limit[1]}, ') and jump.startswith('j ')
                and (window[5][0] or window[6][0])):
            continue
        if (integer(offset), integer(limit[3])) not in reversed_exits:
            continue
        out.add(tuple(integer(item) for item in (offset, limit[3], default[2], constant[3])))
    return out


def _text(part, node):
    return part.clean[node.start:node.end]


def _source_shape(part, start, targets):
    outer = statement(part.clean, start, part.end)
    if not outer or outer.kind != 'if':
        return None
    then, other = outer.parts['then'], outer.parts['other']
    if not other or not then['block'] or not other['block']:
        return None
    one, two = then['stmts'], other['stmts']
    if len(one) != 4 or len(two) != 2 or one[2].kind != 'if' or two[0].kind != 'label':
        return None
    load, increment, guard, advance = one
    label, reset = two
    tested = guard.parts['then']['stmts']
    if guard.parts['other'] or len(tested) != 1 or tested[0].kind != 'goto':
        return None
    if tested[0].parts['target'] != label.parts['name']:
        return None
    if len(re.findall(rf'\bgoto\s+{label.parts["name"]}\s*;', part.body)) != 1:
        return None
    cond_start, cond_end = guard.parts['cond']
    limit = _GUARD.fullmatch(part.clean[cond_start:cond_end])
    if not limit:
        return None
    old = limit['old']
    a, b, c = [_ASSIGNMENT.fullmatch(_text(part, node)) for node in (load, increment, reset)]
    if not all((a, b, c)) or a['lhs'] != old or not re.fullmatch(NUMBER, c['rhs']):
        return None
    read, target, default = [_LVALUE.fullmatch(re.sub(r'\s+', '', expression))
                             for expression in (a['rhs'], b['lhs'], c['lhs'])]
    if (not read or not target or not default or read.groupdict() != target.groupdict()
            or read['type'] != 'u8' or default['base'] != read['base']
            or not re.fullmatch(rf'\(\s*u8\s*\)\s*\(\s*{old}\s*\+\s*1\s*\)', b['rhs'])):
        return None
    witness = tuple(integer(value) for value in (read['offset'], limit['bound'], default['offset'], c['rhs']))
    if witness not in targets or advance.kind != 'simple' or _ESCAPE.search(_text(part, advance)):
        return None
    tail = statement(part.clean, outer.end, part.end)
    if not tail or _text(part, tail) != 'break;':
        return None
    return outer, tail, load, increment, advance, reset, old, limit['bound'], read['base']


def variants(source, name, rows, *, header=''):
    """Use a taken branch for the advancing arm and retain the shared reset."""
    targets = _targets(rows)
    visible = _visible(source, name, header) if targets else None
    if not visible:
        return []
    part, context = visible
    if re.search(rf'\b{ADVANCE}\b|typedef[^;\n]*\bvolatile\b[^;\n]*\b[us]8\b', context):
        return []
    byte_locals = {decl['name'] for decl in locals_for(part) if decl['type'] == 'u8'}
    options = []
    for hit in re.finditer(r'(?m)^(?P<pad>[ \t]*)if\s*\(', part.body):
        start = part.opening + 1 + hit.start()
        if not re.search(rf'\(\s*s8\s*\)\s*{IDENT}\s*\)\s*>=', part.clean[start:start + 540]):
            continue
        found = _source_shape(part, start, targets)
        if not found:
            continue
        outer, tail, load, increment, advance, reset, old, limit, base = found
        if old not in byte_locals or _escaped(part.body, old):
            continue
        segment = source[outer.start:tail.end]
        if re.search(r'/[*/]|#', segment):
            continue
        if re.search(rf'(?m)^\s*#\s*(?:define|undef)\s+(?:{old}|{base}|u8|s8)\b|'
                     rf'\bvolatile\b[^;\n]*\b(?:{old}|{base})\b', context):
            continue
        cond_start, cond_end = outer.parts['cond']
        condition = source[cond_start:cond_end]
        pad = hit['pad']
        inner = pad + '  '
        a, b, c, d = (source[node.start:node.end] for node in (load, increment, reset, advance))
        replacement = (
            f'if ({condition}) {{\n{inner}{a}\n{inner}{b}\n'
            f'{inner}if (((s8) {old}) < {limit}) goto {ADVANCE};\n{pad}}}\n'
            f'{pad}{c}\n{pad}break;\n{ADVANCE}:\n{pad}{d}\n{pad}break;'
        )
        options.append(edit(source, [(outer.start, tail.end, replacement)]))
    return [(FAMILY, options[0])] if len(options) == 1 else []
