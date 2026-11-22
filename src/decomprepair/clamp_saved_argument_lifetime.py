"""Reuse a witnessed saved float for a sampled scale and its clamped argument."""

import re

from .balanced_clamp_argument_stage import _callee_matches, _float_argument
from .clamp_return_local import _field
from .integer_repair_support import IDENT, NUMBER, edit, integer, split_args
from .local_flow import Flow
from .operand_lifetime_repairs import _in_scope, _typed_locals, _visible

FAMILY = 'clamp_saved_argument_lifetime'
_FPR = r'\$f(?:[12]?[0-9]|3[01])'
_SAVED = r'\$f(?:20|22|24|26|28|30)'
_CALL = re.compile(rf'jal ({IDENT}(?:\+0x[0-9a-f]+)?)')
_MULTIPLY = re.compile(rf'mul\.s ({_SAVED}), \$f0, ({_FPR})')
_LOAD = re.compile(rf'lwc1 ({_FPR}), ({NUMBER})(\(\$\w+\))')
_MOVE = re.compile(rf'mov\.s ({_SAVED}), \$f0')
_LITERAL = r'\d+\.\d+[fF]'
_DECL = re.compile(rf'\b(?P<type>f32|float)\s+(?P<name>{IDENT})\s*;')
_DONOR = re.compile(
    rf'(?m)^[ \t]*(?P<name>{IDENT})\s*=\s*(?P<sample>{IDENT})\(\s*{IDENT}\s*,\s*'
    rf'(?P<second>{NUMBER})\s*,\s*(?P<third>{NUMBER})\s*\)\s*;'
)
_SOURCE = re.compile(
    rf'(?m)^[ \t]*(?P<scale_var>(?P<result>{IDENT}))\s*=\s*(?P<sample>{IDENT})\(\s*{IDENT}\s*,'
    rf'\s*{NUMBER}\s*,\s*{NUMBER}\s*\)\s*\*\s*{_LITERAL}\s*;\s*'
    rf'(?P<old>{IDENT})\s*=\s*(?P<field>\*[^;={{}}\n]+?)\s*;\s*'
    rf'(?P=result)\s*=\s*\(\(\s*(?P<scale_read>(?P=result))\s*-\s*(?P=old)\)\s*\*\s*{_LITERAL}\)'
    rf'\s*\+\s*(?P=old)\s*;\s*'
    rf'(?P=field)\s*=\s*(?P=result)\s*;\s*'
    rf'if\s*\(\s*(?P=result)\s*<\s*\(-(?P<bound>{_LITERAL})\)\s*\)\s*'
    rf'\{{\s*(?P=field)\s*=\s*-(?P=bound)\s*;\s*\}}\s*else\s*'
    rf'if\s*\(\s*(?P=result)\s*>\s*(?P=bound)\s*\)\s*\{{\s*(?P=field)\s*=\s*(?P=bound)\s*;\s*\}}\s*'
    rf'(?P<reload>(?P=result))\s*=\s*(?P=field)\s*;\s*(?P<call>{IDENT})\((?P<args>[^;{{}}\n]+)\)\s*;'
)


def _arg_value(register, instruction):
    if instruction == f'move {register}, $zero':
        return 0
    match = re.fullmatch(rf'addiu {re.escape(register)}, \$zero, ({NUMBER})', instruction)
    return integer(match[1]) if match else None


def _donors(rows):
    result = set()
    for j, (left, right) in enumerate(rows):
        move = _MOVE.fullmatch(left)
        if not move or left != right:
            continue
        preceding = [op for op, _ in rows[max(j - 6, 0):j]]
        for index, op in enumerate(preceding):
            call = _CALL.fullmatch(op)
            if not call or index + 1 == len(preceding):
                continue
            second = next((value for prior in reversed(preceding[:index])
                           if (value := _arg_value('$a1', prior)) is not None), None)
            third = _arg_value('$a2', preceding[index + 1])
            if second is not None and third is not None:
                result.add((move[1], call[1], second, third))
    return result


def _witnesses(rows):
    target = [(left, right) for _, left, right in rows if left]
    witnesses = set()
    for j in range(7, len(target) - 2):
        left, right = target[j]
        multiply = _MULTIPLY.fullmatch(left)
        sample = _CALL.fullmatch(target[j - 6][0])
        load = _LOAD.fullmatch(target[j + 1][0])
        if not multiply or not sample or not load or right == left:
            continue
        if not re.fullmatch(rf'mul\.s {_FPR}, \$f0, {re.escape(multiply[2])}', right):
            continue
        register, offset = multiply[1], integer(load[2])
        for end in range(j + 6, min(j + 34, len(target) - 2)):
            first, current = map(_LOAD.fullmatch, target[end])
            if (not first or not current or first[1] != register or current[1] == register
                    or load.groups()[1:] != first.groups()[1:] or first.groups()[1:] != current.groups()[1:]):
                continue
            if not target[end - 2][0].startswith('bc1tl ') or not target[end - 1][0].endswith(f', {load[2]}{load[3]}'):
                continue
            transfer = (f'mfc1 $a3, {register}', f'mfc1 $a3, {current[1]}')
            window = target[end + 1:end + 12]
            for k, row in enumerate(window[:-2]):
                call = _CALL.fullmatch(window[k + 2][0])
                if row == transfer and window[k + 1] == ('nop', 'nop') and call and window[k + 2][0] == window[k + 2][1]:
                    witnesses.add((sample[1], call[1], offset, register))
    return witnesses, _donors(target)


def variants(source, name, rows, *, header=''):
    witnesses, donors = _witnesses(rows)
    visible = _visible(source, name, header) if witnesses and donors else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\btypedef\b[^;\n]*\b(?:volatile|_Atomic)\b[^;\n]*\bf32\s*;', context):
        return []
    ordinary = _typed_locals(part, r'(?:f32|float)')
    declarations = {m['name']: m for m in _DECL.finditer(part.clean, part.opening + 1, part.end)
                    if m['name'] in ordinary and m.start() == ordinary[m['name']][1]}
    try:
        flow = Flow(part, declarations.values())
    except (ValueError, RecursionError):
        return []
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    producers = list(_DONOR.finditer(part.clean, part.opening + 1, part.end))
    proposals = []
    for m in _SOURCE.finditer(part.clean, part.opening + 1, part.end):
        before = part.clean[part.opening + 1:m.start()].rstrip()
        if before and before[-1] not in ';{}:':
            continue
        result = m['result']
        field = _field(m['field'], part.clean[:part.opening])
        call_node = flow.at(m.start('call'))
        if (not field or result in (field[0], m['old']) or result not in flow.names or not call_node
                or any(result in flow.nodes[index].live for index in call_node.successors)):
            continue
        args = split_args(m['args'])
        if len(args) != 6 or not _float_argument(context, m['call'], len(args)):
            continue
        start, stop = args[3]
        fragment = m['args'][start:stop]
        other_arguments = m['args'][:start] + m['args'][stop:]
        if (fragment.strip() != result or re.search(rf'\b{result}\b', other_arguments)
                or macros & set(re.findall(IDENT, m[0]))
                or re.search(r'/[*/]|#', source[m.start():m.end()])):
            continue
        place = m.start('args') + start + len(fragment) - len(fragment.lstrip())
        plan = [(place, place + len(m['result'])), *(m.span(label) for label in ('scale_var', 'scale_read', 'reload'))]
        registers = {register for sample, call, offset, register in witnesses
                     if offset == field[1] and _callee_matches(sample, m['sample']) and _callee_matches(call, m['call'])}
        for prior in sorted(producers, key=lambda item: abs(item.start() - m.start())):
            carry = prior['name']
            if carry in re.findall(IDENT, m[0]) or carry not in flow.names or not _in_scope(part, declarations[carry].start(), m.start()):
                continue
            if not all(flow.dead(carry, m.start(label)) for label in ('scale_var', 'reload')):
                continue
            if not any(
                reg in registers and _callee_matches(callee, prior['sample'])
                and (second, third) == (integer(prior['second']), integer(prior['third']))
                for reg, callee, second, third in donors
            ):
                continue
            changed = edit(source, [(start, stop, carry) for start, stop in plan])
            if all(previous != changed for _, previous in proposals):
                proposals.append((FAMILY, changed))
            if len(proposals) == 4:
                return proposals
    return proposals
