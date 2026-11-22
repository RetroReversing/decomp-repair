"""Reuse a witnessed saved float for the sign preserved across a square."""

import re
from collections import Counter

from .balanced_clamp_predicates import _LUI, _ORI, _bits
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .local_flow import Flow
from .operand_lifetime_repairs import _in_scope, _typed_locals, _visible
from .trig_axis_reuse import _CALL, _DECL, _SAVED

FAMILY = 'saved_quadratic_sign_holder'
_LITERAL = r'\d+\.\d+[fF]'
_CALL_SOURCE = rf'(?P<callee>{IDENT})\(\s*{IDENT}\s*,\s*(?P<a1>{NUMBER})\s*,\s*(?P<a2>{NUMBER})\s*\)'
_SIGNED = re.compile(
    rf'(?m)^\s*(?P<axis>{IDENT})\s*=\s*{_CALL_SOURCE}\s*;\s*'
    rf'(?P<sign>{IDENT})\s*=\s*(?P=axis)\s*;\s*'
    rf'(?P=axis)\s*=\s*(?P<wrap>\()?\s*(?P=axis)\s*\*\s*(?P=axis)\s*(?(wrap)\))'
    rf'(?:\s*\*\s*{_LITERAL})?\s*;\s*'
    rf'if\s*\(\s*(?P<test>(?P=sign))\s*<\s*0\.0[fF]\s*\)'
    rf'\s*\{{\s*(?P=axis)\s*=\s*-(?P=axis)\s*;\s*\}}'
)
_DONOR = re.compile(
    rf'(?m)^[ \t]*(?P<holder>{IDENT})\s*=\s*{_CALL_SOURCE}\s*\*\s*(?P<gain>{_LITERAL})\s*;'
)
_A1 = re.compile(rf'addiu \$a1, \$zero, ({NUMBER})')
_A2 = re.compile(rf'addiu \$a2, \$zero, ({NUMBER})')
_SIGN_TEST = re.compile(rf'c\.lt\.s ({_SAVED}), \$f0')
_OTHER_TEST = re.compile(r'c\.lt\.s (\$f[1-9]\d*), \$f0')
_SCALED_RETURN = re.compile(rf'mul\.s ({_SAVED}), \$f0, (\$f\d+)')


def _witnesses(rows):
    signed, donors = Counter(), set()
    for index in range(1, len(rows) - 14):
        callee = _CALL.fullmatch(rows[index][1])
        a1, a2 = _A1.fullmatch(rows[index - 1][1]), _A2.fullmatch(rows[index + 1][1])
        if not (callee and a1 and a2 and all(left == right for _, left, right in rows[index - 1:index + 2])):
            continue
        call = callee[1], integer(a1[1]), integer(a2[1])
        window = rows[index + 2:index + 15]
        left = [op for _, op, _ in window]
        right = [op for _, _, op in window]
        source_axis = re.fullmatch(rf'mov\.s ({_SAVED}), \$f0', left[0])
        if source_axis and left[0] == right[0]:
            for step, op in enumerate(left[2:8], 2):
                match, other = _SIGN_TEST.fullmatch(op), _OTHER_TEST.fullmatch(right[step])
                if not match or not other or match[1] == other[1]:
                    continue
                target, current = match[1], other[1]
                axis = source_axis[1]
                if (target != axis and f'mov.s {target}, {axis}' in left[1:step]
                        and f'mov.s {current}, {axis}' in right[1:step]
                        and left[step + 1:step + 3] == ['nop', 'nop']
                        and left[step + 3].startswith('bc1f ') and left[step + 3] == right[step + 3]
                        and left[step + 5] == right[step + 5] == f'neg.s {axis}, {axis}'):
                    signed[(*call, target)] += 1
        high, low = _LUI.fullmatch(left[0]), _ORI.fullmatch(left[1])
        scaled = _SCALED_RETURN.fullmatch(left[4])
        if (high and low and scaled and left[:5] == right[:5]
                and left[2:4] == [f'mtc1 $at, {scaled[2]}', 'nop']):
            donors.add((*call, integer(high[1]) << 16 | integer(low[1]), scaled[1]))
    return signed, donors


def _call(match):
    return match['callee'], integer(match['a1']), integer(match['a2'])


def variants(source, name, rows, *, header=''):
    signed, donors = _witnesses(rows)
    visible = _visible(source, name, header) if signed and donors else None
    if not visible:
        return []
    part, context = visible
    typedefs = re.findall(r'\btypedef\s+([^;{}]+?)\s+f32\s*;', context)
    if any(alias.strip() != 'float' for alias in typedefs):
        return []
    types = _typed_locals(part, r'(?:f32|float)')
    declarations = {m['name']: m for m in _DECL.finditer(part.clean, part.opening + 1, part.end)
                    if m['name'] in types and m.start() == types[m['name']][1]}
    try:
        flow = Flow(part, declarations.values())
    except (ValueError, RecursionError):
        return []
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    hits = list(_SIGNED.finditer(part.clean, part.opening + 1, part.end))
    proposals = []
    for match in _DONOR.finditer(part.clean, part.opening + 1, part.end):
        holder = match['holder']
        regs = {reg for *call, bits, reg in donors if tuple(call) == _call(match) and bits == _bits(match['gain'])}
        if not regs or holder not in flow.names or types[holder][0] in macros or macros & set(re.findall(IDENT, match[0])):
            continue
        for reg in sorted(regs):
            wanted = {key[:-1]: count for key, count in signed.items() if key[-1] == reg and key[0] == match['callee']}
            selected = [hit for hit in hits if _call(hit) in wanted]
            if not 1 <= len(selected) <= 4 or Counter(_call(hit) for hit in selected) != wanted:
                continue
            changes = []
            for hit in selected:
                axis, sign = hit['axis'], hit['sign']
                last = flow.at(hit.start('test'))
                if (axis == sign or holder in (axis, sign) or sign not in flow.names or not last
                        or any(sign in flow.nodes[node].live for node in last.successors)
                        or not _in_scope(part, declarations[holder].start(), hit.start('sign'))
                        or not flow.dead(holder, hit.start('sign'))
                        or macros & set(re.findall(IDENT, hit[0]))):
                    break
                changes.extend([(*hit.span('sign'), holder), (*hit.span('test'), holder)])
            else:
                variant = (FAMILY, edit(source, changes))
                if variant not in proposals:
                    proposals.append(variant)
                if len(proposals) == 4:
                    return proposals
    return proposals
