"""Keep a scaled input in a witnessed saved local before blending it."""

import re
from collections import Counter

from .balanced_clamp_predicates import _bits, _constant
from .clamp_return_local import _field
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .local_flow import Flow
from .operand_lifetime_repairs import _in_scope, _typed_locals, _visible
from .trig_axis_reuse import _CALL, _DECL, _PRIOR, _SAVED, _confirmed_global_loads

FAMILY = 'saved_scaled_blend_input'
_LITERAL = r'\d+\.\d+[fF]'
_FPR = r'\$f\d+'
_PRODUCT = re.compile(rf'mul\.s ({_SAVED}), ({_FPR}), ({_FPR})')
_CANDIDATE = re.compile(rf'mul\.s ({_FPR}), ({_FPR}), ({_FPR})')
_LOAD = re.compile(rf'lwc1 ({_FPR}), ({NUMBER})\(\$\w+\)')
_CAST = re.compile(rf'\(\s*\(\s*(?P<type>f32|float)\s*\)\s*(?P<value>{IDENT})\s*\)')
_SOURCE = re.compile(
    rf'(?m)^(?P<pad>[ \t]*)(?P<old>{IDENT})\s*=\s*(?P<field>\*[^;={{}}\n]+)\s*;\s*'
    rf'{IDENT}\s*=\s*\(\(\s*(?P<term>\(\s*(?P<input>{IDENT}|{_CAST.pattern})\s*\*\s*'
    rf'(?P<gain>{_LITERAL})\s*\))\s*-\s*(?P=old)\s*\)\s*\*\s*(?P=gain)\s*\)'
    rf'\s*\+\s*(?P=old)\s*;'
)


def _observed(rows):
    target = [(i, left) for i, (_, left, _) in enumerate(rows) if left]
    measured = Counter()
    for at in range(7, len(rows) - 4):
        _, left, right = rows[at]
        wanted, actual = _PRODUCT.fullmatch(left), _CANDIDATE.fullmatch(right)
        if not wanted or not actual or wanted[1] == actual[1] or wanted[3] != actual[3]:
            continue
        register, operand, factor = wanted.groups()
        scratch = actual[1]
        _, load, alternate = rows[at + 1]
        field = _LOAD.fullmatch(load)
        if not field or load != alternate:
            continue
        _, subtract, other = rows[at + 2]
        form = re.fullmatch(rf'sub\.s ({_FPR}), {re.escape(register)}, {re.escape(field[1])}', subtract)
        if not form or other != f'sub.s {form[1]}, {scratch}, {field[1]}':
            continue
        result = form[1]
        blend = f'mul.s {result}, {result}, {factor}'
        finish = f'add.s {result}, {result}, {field[1]}'
        if [tuple(row[1:]) for row in rows[at + 3:at + 5]] != [(blend, blend), (finish, finish)]:
            continue
        cast = (operand == register and actual[2] == scratch
                and rows[at - 1][1] == f'cvt.s.w {register}, {register}'
                and rows[at - 1][2] == f'cvt.s.w {scratch}, {scratch}')
        if cast:
            move = re.fullmatch(rf'mtc1 (\$\w+), {re.escape(register)}', rows[at - 3][1])
            if not move or rows[at - 3][2] != f'mtc1 {move[1]}, {scratch}':
                continue
            callee = None
        elif operand == actual[2] == '$f0':
            call = next((m[1] for _, op, other in reversed(rows[at - 7:at])
                         if op == other and (m := _CALL.fullmatch(op))), None)
            if not call:
                continue
            callee = call
        else:
            continue
        # The factor is introduced immediately before this conversion or call product.
        high = None
        for start in range(at - 5, at):
            if rows[start][1] == rows[start][2] == f'mtc1 $at, {factor}':
                high = next((index for index, (row, _) in enumerate(target) if row == start), None)
                break
        if high is None:
            continue
        bits = _constant(target, high + 1, factor)
        if bits is not None:
            measured[integer(field[2]), bits, callee, register] += 1
    return measured


def variants(source, name, rows, *, header=''):
    measured = _observed(rows)
    visible = _visible(source, name, header) if 1 <= sum(measured.values()) <= 4 else None
    if not visible:
        return []
    part, context = visible
    typedefs = re.findall(r'\btypedef\s+([^;{}]+?)\s+f32\s*;', context)
    if any(alias.strip() != 'float' for alias in typedefs):
        return []
    floats = _typed_locals(part, r'(?:f32|float)')
    ints = _typed_locals(part, r'(?:s32|int|s8|s16|u8|u16)')
    declarations = {m['name']: m for m in _DECL.finditer(part.clean, part.opening + 1, part.end)
                    if m['name'] in floats and m.start() == floats[m['name']][1]}
    try:
        flow = Flow(part, declarations.values())
    except (ValueError, RecursionError):
        return []
    targets = [(i, left, other) for i, (_, left, other) in enumerate(rows) if left]
    evidence = {(register, offset, symbol) for _, register, offset, symbol in _confirmed_global_loads(targets)}
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    prefix = part.clean[:part.opening]
    requests = []
    for hit in _SOURCE.finditer(part.clean, part.opening + 1, part.end):
        before = part.clean[part.opening + 1:hit.start()].rstrip()
        field = _field(hit['field'], prefix)
        if not field or not before or before[-1] not in ';{}:' or macros & set(re.findall(IDENT, hit[0])):
            continue
        if hit['type']:
            if (hit['value'] not in ints or ints[hit['value']][0] in macros
                    or not _in_scope(part, ints[hit['value']][1], hit.start())):
                continue
            callee = None
        else:
            if (hit['input'] not in floats or floats[hit['input']][0] in macros
                    or not _in_scope(part, floats[hit['input']][1], hit.start())):
                continue
            prior = re.search(rf'\b{hit["input"]}\s*=\s*({IDENT})\([^;{{}}\n]+\);$', before)
            if not prior or prior[1] in macros:
                continue
            callee = prior[1]
        requests.append(((field[1], _bits(hit['gain']), callee), hit))
    proposals = []
    for donor in _PRIOR.finditer(part.clean, part.opening + 1, part.end):
        holder, field = donor['local'], _field(donor['field'], prefix)
        if (not field or holder not in flow.names or floats[holder][0] in macros
                or macros & set(re.findall(IDENT, donor[0]))):
            continue
        for register, offset, symbol in sorted(evidence):
            if (offset, symbol) != (field[1], donor['global']):
                continue
            wanted = {key[:3]: count for key, count in measured.items() if key[3] == register}
            selected = [(key, hit) for key, hit in requests if key in wanted]
            if not wanted or Counter(key for key, _ in selected) != wanted:
                continue
            changes = []
            for _, hit in selected:
                if (donor.end() >= hit.start() or not _in_scope(part, declarations[holder].start(), hit.start())
                        or not flow.dead(holder, hit.start('old')) or re.search(rf'\b{holder}\b', hit[0])):
                    break
                pad = hit['pad']
                if hit['type']:
                    binding = (f'{pad}{holder} = ({hit["type"]}) {hit["value"]};\n'
                               f'{pad}{holder} *= {hit["gain"]};\n')
                else:
                    binding = f'{pad}{holder} = {source[hit.start("term"):hit.end("term")]};\n'
                changes.extend([(hit.start(), hit.start(), binding), (*hit.span('term'), holder)])
            else:
                candidate = (FAMILY, edit(source, changes))
                if candidate not in proposals:
                    proposals.append(candidate)
                if len(proposals) == 4:
                    return proposals
    return proposals
