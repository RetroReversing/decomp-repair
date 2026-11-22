"""Reuse a guarded field local for a sampled phase and its in-place scale."""

import re
import struct
from collections import defaultdict

from .balanced_clamp_predicates import _LUI, _ORI, _bits
from .clamp_return_local import _field
from .clamp_saved_argument_lifetime import _arg_value
from .float_clamp_scale_stage import _witnesses as scale_witnesses
from .integer_repair_support import IDENT, NUMBER, edit, integer, refs
from .local_flow import Flow
from .operand_lifetime_repairs import _in_scope, _typed_locals, _visible

FAMILY = 'sampled_phase_axis_stage'
_SAVED = r'\$f(?:20|22|24|26|28|30)'
_FPR = r'\$f(?:[12]?[0-9]|3[01])'
_LOAD = re.compile(rf'lwc1 ({_FPR}), ({NUMBER})(\(\$\w+\))')
_NEGATE = re.compile(rf'neg\.s ({_SAVED}), \$f0')
_CALL = re.compile(rf'jal ({IDENT})')
_DECL = re.compile(rf'\b(?P<type>f32|float)\s+(?P<name>{IDENT})\s*;')
_LITERAL = r'\d+\.\d+[fF]'
_DONOR = re.compile(
    rf'(?m)^[ \t]*(?P<local>{IDENT})\s*=\s*(?P<field>\*[^;={{}}\n]+?)\s*;\s*'
    rf'{IDENT}\s*=\s*1\s*;\s*if\s*\(!\((?P=local)\s*<=\s*(?P<limit>{_LITERAL})\)\)'
)
_START = re.compile(
    rf'(?m)^[ \t]*(?P<axis>{IDENT})\s*=\s*-(?P<call>{IDENT})\(\s*(?P<input>{IDENT})\s*,\s*'
    rf'(?P<second>{NUMBER})\s*,\s*(?P<third>{NUMBER})\s*\)\s*;'
)
_SCALE = re.compile(
    rf'(?m)^[ \t]*(?P<old>{IDENT})\s*=\s*(?P<field>\*[^;={{}}\n]+?)\s*;\s*'
    rf'(?P<product>(?P<result>{IDENT})\s*=\s*(?P<axis>{IDENT})\s*\*\s*(?P<factor>{_LITERAL});)\s*'
    rf'(?P<blend>(?P=result)\s*=\s*\(\(\s*(?P<used>(?P=result))\s*-\s*(?P=old)\)\s*\*\s*{_LITERAL}\)'
    rf'\s*\+\s*(?P=old);)'
)


def _missing_lifetimes(rows):
    targets = [(index, left, right) for index, (_, left, right) in enumerate(rows) if left]
    loaded, sampled = [], []
    for j, (index, line, current) in enumerate(targets):
        load, other = _LOAD.fullmatch(line), _LOAD.fullmatch(current)
        if load and other and re.fullmatch(_SAVED, load[1]) and load[1] != other[1] and load.groups()[1:] == other.groups()[1:]:
            after = targets[j + 1:j + 34]
            if (after and after[0][1].startswith(f'c.le.s {load[1]}, ')
                    and after[0][2].startswith(f'c.le.s {other[1]}, ')
                    and any(left.startswith(f'swc1 {load[1]}, ') and right == left.replace(load[1], other[1], 1)
                            for _, left, right in after)):
                loaded.append((index, integer(load[2])))
        negate = _NEGATE.fullmatch(line)
        if not negate or line == current or not _NEGATE.fullmatch(current):
            continue
        lead = targets[max(0, j - 10):j]
        for n, (_, line, _) in enumerate(lead[:-1]):
            call = _CALL.fullmatch(line)
            if not call:
                continue
            third = _arg_value('$a2', lead[n + 1][1])
            second = next((value for _, op, _ in reversed(lead[:n])
                           if (value := _arg_value('$a1', op)) is not None), None)
            if second is not None and third is not None:
                sampled.append((index, call[1], second, third))
    return {(offset, callee, second, third) for start, offset in loaded for end, callee, second, third in sampled if start < end}


def _safe_region(flow, old, start, stop, entry):
    for node in flow.nodes:
        inside = start <= node.start < stop
        for index in node.successors:
            successor = flow.nodes[index]
            enters = start <= successor.start < stop
            if inside and not enters and old in successor.live:
                return False
            if enters and not inside and successor is not entry:
                return False
    return True


def variants(source, name, rows, *, header=''):
    phases, scales = _missing_lifetimes(rows), scale_witnesses(rows)
    visible = _visible(source, name, header) if phases and scales else None
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
    prefix = part.clean[:part.opening]
    donors = [(m, field) for m in _DONOR.finditer(part.clean, part.opening + 1, part.end)
              if (field := _field(m['field'], prefix))]
    proposals = []
    for start in _START.finditer(part.clean, part.opening + 1, part.end):
        old = start['axis']
        if old not in flow.names:
            continue
        scale = _SCALE.search(part.clean, start.end(), min(start.end() + 4096, part.end))
        if not scale or scale['axis'] != old or old in (scale['old'], scale['result']):
            continue
        field = _field(scale['field'], prefix)
        if not field or field[0] == old:
            continue
        try:
            bits = struct.unpack('>I', struct.pack('>f', float(scale['factor'][:-1])))[0]
        except OverflowError:
            continue
        if (field[1], bits) not in scales:
            continue
        body = part.clean[start.start():scale.end()]
        if macros & set(re.findall(IDENT, body)) or re.search(r'/[*/]|#', source[start.start():scale.end()]):
            continue
        entry = flow.at(start.start('axis'))
        if not entry or not _safe_region(flow, old, start.start(), scale.end(), entry):
            continue
        fallback = re.compile(rf'\b{old}\s*=\s*{start["call"]}\(\s*{start["input"]}\s*,\s*{NUMBER}\s*,\s*{NUMBER}\s*\)')
        if not fallback.search(body):
            continue
        for donor, earlier in donors:
            carry = donor['local']
            if (donor.end() >= start.start() or carry not in flow.names or re.search(rf'\b{carry}\b', body)
                    or not _in_scope(part, declarations[carry].start(), start.start())
                    or not flow.dead(carry, start.start('axis'))):
                continue
            if (earlier[1], start['call'], integer(start['second']), integer(start['third'])) not in phases:
                continue
            edits = [(use.start(), use.end(), carry) for use in refs(part, declarations[old])
                     if start.start() <= use.start() < scale.start('product')]
            edits += [(*scale.span('product'), f'{carry} *= {scale["factor"]};'), (*scale.span('used'), carry)]
            proposals.append((FAMILY, edit(source, edits)))
            if len(proposals) == 4:
                return proposals
    return proposals


_STAGED = re.compile(
    rf'(?m)^[ \t]*(?P<old>{IDENT})\s*=\s*(?P<field>\*[^;={{}}\n]+?)\s*;\s*'
    rf'(?P<axis>{IDENT})\s*\*=\s*(?P<factor>{_LITERAL})\s*;\s*'
    rf'{IDENT}\s*=\s*\(\(\s*(?P=axis)\s*-\s*(?P=old)\s*\)\s*\*\s*{_LITERAL}\)'
    rf'\s*\+\s*(?P=old);'
)
_MTC = re.compile(rf'mtc1 \$at, ({_FPR})')


def _literal_at(code, at):
    if at < 2 or not (transfer := _MTC.fullmatch(code[at])):
        return None
    low = _ORI.fullmatch(code[at - 1])
    high = _LUI.fullmatch(code[at - (2 if low else 1)])
    if high:
        return transfer[1], integer(high[1]) << 16 | (integer(low[1]) if low else 0)
    return None


def _matched_guard_holders(rows, target):
    result = defaultdict(list)
    for i, line in enumerate(target[:-5]):
        load = _LOAD.fullmatch(line)
        literal = _literal_at(target, i + 3)
        if not load or not literal or not re.fullmatch(_SAVED, load[1]) or not _ORI.fullmatch(target[i + 2]):
            continue
        other = _LOAD.fullmatch(rows[i][1])
        comparison = f'c.le.s {load[1]}, {literal[0]}'
        if (not other or other.groups()[1:] != load.groups()[1:]
                or target[i + 4:i + 6] != ['nop', comparison]):
            continue
        matched = all(a == b for a, b in rows[i:i + 6])
        result[integer(load[2]), literal[1]].append(load[1] if matched else None)
    return result


def _staged_phase_witnesses(rows, target):
    result = set()
    for i in range(7, len(rows) - 4):
        left, right = rows[i]
        axis, old_axis = _NEGATE.fullmatch(left), _NEGATE.fullmatch(right)
        if not axis or not old_axis or axis[1] == old_axis[1]:
            continue
        upper, old_upper = map(_MTC.fullmatch, rows[i - 1])
        if not upper or not old_upper or (upper[1], old_upper[1]) != (old_axis[1], axis[1]):
            continue
        if rows[i + 1] != (f'c.le.s {axis[1]}, {upper[1]}', f'c.le.s {old_axis[1]}, {old_upper[1]}'):
            continue
        call, second, third = _CALL.fullmatch(target[i - 5]), _arg_value('$a1', target[i - 6]), _arg_value('$a2', target[i - 4])
        if not call or second is None or third is None or any(a != b for a, b in rows[i - 6:i - 1]):
            continue
        mul = re.compile(rf'mul\.s {re.escape(axis[1])}, {re.escape(axis[1])}, ({_FPR})')
        for j in range(i + 4, min(i + 150, len(rows) - 2)):
            product, load = mul.fullmatch(target[j]), _LOAD.fullmatch(target[j + 1])
            if not product or not load or rows[j + 1][0] != rows[j + 1][1]:
                continue
            scale = _literal_at(target, j - 2)
            subtract = re.fullmatch(rf'sub\.s ({_FPR}), {re.escape(axis[1])}, {re.escape(load[1])}', target[j + 2])
            if (scale and scale[0] == product[1] and subtract and target[j - 1] == 'nop'
                    and all(a == b for a, b in rows[j - 3:j])
                    and rows[j][1] == f'mul.s {old_axis[1]}, {old_axis[1]}, {product[1]}'
                    and rows[j + 2][1] == f'sub.s {subtract[1]}, {old_axis[1]}, {load[1]}'):
                result.add((call[1], second, third, integer(load[2]), scale[1], axis[1]))
    return result


def staged_variants(source, name, rows, *, header=''):
    """Reuse a matched guarded holder when the phase already scales in place."""
    aligned = [(left, right) for _, left, right in rows if left]
    target = [left for left, _ in aligned]
    demanded = _staged_phase_witnesses(aligned, target)
    visible = _visible(source, name, header) if demanded else None
    if not visible:
        return []
    guarded = _matched_guard_holders(aligned, target)
    part, context = visible
    typedefs = re.findall(r'\btypedef\s+([^;{}]+?)\s+f32\s*;', context)
    if any(alias.strip() != 'float' for alias in typedefs):
        return []
    ordinary = _typed_locals(part, r'(?:f32|float)')
    declarations = {m['name']: m for m in _DECL.finditer(part.clean, part.opening + 1, part.end)
                    if m['name'] in ordinary and m.start() == ordinary[m['name']][1]}
    try:
        flow = Flow(part, declarations.values())
    except (ValueError, RecursionError):
        return []
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    prefix = part.clean[:part.opening]
    donors = defaultdict(list)
    for match in _DONOR.finditer(part.clean, part.opening + 1, part.end):
        field = _field(match['field'], prefix)
        if field:
            donors[field[1], _bits(match['limit'])].append(match)
    holders = [(match, register) for key, matches in donors.items() if len(matches) == len(guarded[key])
               for match, register in zip(matches, guarded[key]) if register]
    result = []
    for start in _START.finditer(part.clean, part.opening + 1, part.end):
        old = start['axis']
        scale = _STAGED.search(part.clean, start.end(), min(start.end() + 4096, part.end))
        if old not in flow.names or not scale or scale['axis'] != old or scale['old'] == old:
            continue
        field = _field(scale['field'], prefix)
        if not field:
            continue
        key = (start['call'], integer(start['second']), integer(start['third']), field[1], _bits(scale['factor']))
        body = part.clean[start.start():scale.end()]
        if macros & set(re.findall(IDENT, body)) or re.search(r'/[*/]|#', source[start.start():scale.end()]):
            continue
        entry = flow.at(start.start('axis'))
        if not entry or not _safe_region(flow, old, start.start(), scale.end(), entry):
            continue
        if not re.search(rf'\b{old}\s*=\s*{start["call"]}\(\s*{start["input"]}\s*,\s*{NUMBER}\s*,\s*{NUMBER}\s*\)', body):
            continue
        for donor, register in holders:
            carry = donor['local']
            if (donor.end() >= start.start() or (*key, register) not in demanded or carry not in flow.names
                    or carry in macros or re.search(rf'\b{carry}\b', body)
                    or not all(_in_scope(part, declarations[carry].start(), p) for p in (start.start(), scale.end()))
                    or not flow.dead(carry, start.start('axis'))):
                continue
            changes = [(use.start(), use.end(), carry) for use in refs(part, declarations[old])
                       if start.start() <= use.start() < scale.end()]
            candidate = (FAMILY, edit(source, changes))
            if candidate not in result:
                result.append(candidate)
            if len(result) == 3:
                return result
    return result
