"""Pair a float argument reload with two earlier witnessed predicate stages."""

import re
import struct
from collections import Counter
from itertools import combinations

from .balanced_float_predicate_return import _PREDICATES, _earlier
from .clamp_return_local import _field
from .compiler_phase_repairs import fresh
from .integer_repair_support import IDENT, NUMBER, edit, integer, split_args
from .local_flow import Flow
from .operand_lifetime_repairs import _escaped, _in_scope, _typed_locals, _visible

FAMILY = 'balanced_clamp_argument_stage'
_SAVED = r'\$f(?:20|22|24|26|28|30)'
_LOAD = re.compile(rf'lwc1 ({_SAVED}), ({NUMBER})(\(\$\w+\))')
_STORE = re.compile(rf'swc1 (\$f\d+), ({NUMBER})(\(\$\w+\))')
_CALL = re.compile(rf'jal ({IDENT}(?:\+0x[0-9a-f]+)?)')
_LITERAL = r'\d+\.\d+[fF]'
_DECL = re.compile(rf'\b(?P<type>f32|float)\s+(?P<name>{IDENT})\s*;')
_CLAMP_ARGUMENT = re.compile(
    rf'(?m)^[ \t]*(?P<field>\*[^;={{}}\n]+?)\s*=\s*(?P<result>{IDENT})\s*;\s*'
    rf'if\s*\(\s*(?P=result)\s*<\s*\(-(?P<bound>{_LITERAL})\)\s*\)\s*'
    rf'\{{\s*(?P=field)\s*=\s*-(?P=bound)\s*;\s*\}}\s*'
    rf'else\s*if\s*\(\s*(?P=result)\s*>\s*(?P=bound)\s*\)\s*'
    rf'\{{\s*(?P=field)\s*=\s*(?P=bound)\s*;\s*\}}\s*'
    rf'^(?P<pad>[ \t]*)(?P<callee>{IDENT})\((?P<args>[^;{{}}\n]+)\)\s*;'
)


def _callee_matches(rendered, source):
    if rendered == source:
        return True
    base = re.fullmatch(r'func_([0-9a-fA-F]{8})\+0x([0-9a-f]+)', rendered)
    named = re.fullmatch(r'func_([0-9a-fA-F]{8})', source)
    return bool(base and named and int(named[1], 16) == int(base[1], 16) + int(base[2], 16))


def _arguments(rows, target):
    for j in range(2, len(target) - 4):
        index, op = target[j]
        load = _LOAD.fullmatch(op)
        store = _STORE.fullmatch(target[j - 1][1])
        if (not load or not store or store.groups()[1:] != load.groups()[1:]
                or not target[j - 2][1].startswith('bc1tl ') or rows[index][0] == ' '):
            continue
        window = target[j + 1:j + 14]
        for k, (_, line) in enumerate(window[:-2]):
            if line != f'mfc1 $a3, {load[1]}' or window[k + 1][1] != 'nop':
                continue
            call = _CALL.fullmatch(window[k + 2][1])
            end = window[k + 2][0]
            relevant = {right for _, _, right in rows[index:end + 1]}
            if call and f'lw $a3, {load[2]}{load[3]}' in relevant and f'jal {call[1]}' in relevant:
                yield index, call[1], integer(load[2])


def _stage_predicate(source, guard, first_decl, temporary):
    position = first_decl[1]
    line = source.rfind('\n', 0, position) + 1
    indent = source[line:position]
    if indent.strip():
        return None
    pad = guard['pad']
    placement = guard.start('pad')
    return [(position, position, f'{first_decl[0]} {temporary};\n{indent}'),
            (placement, placement, f'{pad}{temporary} = {guard["first"]} ^ 1;\n'),
            (*guard.span('inverted'), temporary)]


def _predicate_sites(source, part, ints, macros):
    for guard in _PREDICATES.finditer(part.clean, part.opening + 1, part.end):
        flags = (guard['first'], guard['second'])
        if flags[0] == flags[1] or any(
            flag not in ints or not _in_scope(part, ints[flag][1], guard.start()) or _escaped(part.body, flag)
            for flag in flags
        ):
            continue
        if macros & set(re.findall(IDENT, guard[0])) or re.search(r'/[*/]|#', source[guard.start():guard.end()]):
            continue
        try:
            limit = struct.unpack('>I', struct.pack('>f', float(guard['limit'][:-1])))[0]
        except OverflowError:
            continue
        yield guard, limit


def _float_argument(context, callee, count):
    types = re.findall(rf'\b(?:int|s32|void|f32|float)\s+{callee}\s*\(([^();]+)\)\s*;', context)
    return any(len(params) == count and re.fullmatch(rf'\s*(?:f32|float)(?:\s+{IDENT})?\s*', params[3])
               for prototype in types if (params := prototype.split(',')))


def variants(source, name, rows, *, header=''):
    target = [(i, left) for i, (_, left, _) in enumerate(rows) if left]
    arguments = list(_arguments(rows, target))
    visible = _visible(source, name, header) if arguments else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\btypedef\b[^;\n]*\b(?:volatile|_Atomic)\b[^;\n]*\bf32\s*;', context):
        return []
    inversions = list(_earlier(rows, target, same_comparisons=False))
    ints = _typed_locals(part, r'(?:s32|int)')
    floats = _typed_locals(part, r'(?:f32|float)')
    declarations = [m for m in _DECL.finditer(part.clean, part.opening + 1, part.end)
                    if m['name'] in floats and m.start() == floats[m['name']][1]]
    try:
        flow = Flow(part, declarations)
    except (ValueError, RecursionError):
        return []
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    guards = list(_predicate_sites(source, part, ints, macros))
    temporaries = [fresh(source, header, 'repair_bound_result'), fresh(source, header, 'repair_second_bound')]
    proposals = []
    for m in _CLAMP_ARGUMENT.finditer(part.clean, part.opening + 1, part.end):
        local = m['result']
        field = _field(m['field'], part.clean[:part.opening])
        if (not field or local not in floats or local == field[0] or _escaped(part.body, local)
                or not _in_scope(part, floats[local][1], m.start()) or local not in flow.names
                or not flow.dead(local, m.start('callee'))):
            continue
        if macros & set(re.findall(IDENT, m[0])) or re.search(r'/[*/]|#', source[m.start():m.end()]):
            continue
        args = split_args(m['args'])
        if len(args) != 6 or not _float_argument(context, m['callee'], len(args)):
            continue
        start, stop = args[3]
        if _field(m['args'][start:stop], part.clean[:part.opening]) != field:
            continue
        if re.search(rf'\b{local}\b', m['args']) or re.search(r'[=]|\+\+|--', m['args']):
            continue
        call = next((i for i, rendered, offset in arguments
                     if offset == field[1] and _callee_matches(rendered, m['callee'])), None)
        if call is None:
            continue
        counts = Counter(bits for start, _, bits in inversions if start < call)
        matching = [(guard, bits) for guard, bits in guards if guard.end() < m.start() and counts[bits]]
        related = {bits for _, bits in matching if sum(value == bits for _, value in matching) <= counts[bits]}
        matching = [(guard, bits) for guard, bits in matching if bits in related]
        for (earliest, _), (latest, _) in combinations(matching, 2):
            if len({earliest['first'], earliest['second'], latest['first'], latest['second']}) != 4:
                continue
            before = _stage_predicate(source, earliest, ints[earliest['first']], temporaries[0])
            after = _stage_predicate(source, latest, ints[latest['first']], temporaries[1])
            if not before or not after:
                continue
            field_text = source[slice(*m.span('field'))]
            pad, place = m['pad'], m.start('pad')
            absolute = m.start('args')
            argument = m['args'][start:stop]
            begin_text = absolute + start + len(argument) - len(argument.lstrip())
            end_text = absolute + start + len(argument.rstrip())
            edits = [(place, place, f'{pad}{local} = {field_text};\n'), (begin_text, end_text, local)]
            proposals.append((FAMILY, edit(source, [*before, *after, *edits])))
            if len(proposals) == 4:
                return proposals
    return proposals
