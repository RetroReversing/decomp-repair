"""Reuse a witnessed saved float for an unchanged sampled value."""

import re
from collections import Counter

from .balanced_clamp_predicates import _LUI, _ORI, _bits
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .local_flow import Flow
from .operand_lifetime_repairs import _in_scope, _typed_locals, _visible
from .trig_axis_reuse import _CALL, _DECL, _SAVED

FAMILY = 'saved_quadratic_sign_holder'
CALL_AXIS = 'saved_argument_sample_holder'
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

_CALL_SAMPLE = re.compile(
    rf'(?m)^[ \t]*(?P<axis>{IDENT})\s*=\s*{_CALL_SOURCE}\s*;\s*'
    rf'(?P<copy>{IDENT})\s*=\s*(?P=axis)\s*;\s*'
    rf'(?P=axis)\s*=\s*(?P=axis)\s*\*\s*{_LITERAL}\s*;'
)
_SAVED_COPY = re.compile(rf'mov\.s ({_SAVED}), ({_SAVED})')
_ARGUMENT_CONSUMER = re.compile(rf'\b({IDENT})\s*\(([^();{{}}\n]+)\)')


def _selector(pattern, text, register):
    if text == f'move {register}, $zero':
        return 0
    match = pattern.fullmatch(text)
    return integer(match[1]) if match else None


def _outgoing_sample(rows, index):
    lead = rows[index + 2:index + 12]
    anchors = [(target, candidate) for _, target, candidate in lead
               if target == candidate and re.fullmatch(rf'mov\.s {_SAVED}, \$f0', target)]
    if len(anchors) != 1:
        return []
    axis = anchors[0][0].split()[1].rstrip(',')
    for _, target, candidate in lead:
        copy, other = _SAVED_COPY.fullmatch(target), _SAVED_COPY.fullmatch(candidate)
        if not copy or not other or copy[2] != axis or other[2] != axis or copy[1] == other[1]:
            continue
        old, new = copy[1], other[1]
        nearby = rows[index + 12:index + 160]
        word = (f'mfc1 $a1, {old}', f'mfc1 $a1, {new}')
        float_arg = (f'mov.s $f12, {old}', f'mov.s $f12, {new}')
        if sum((left, right) == word for _, left, right in nearby) < 2:
            continue
        consumers = set()
        for at, (_, left, right) in enumerate(nearby):
            if at and (left, right) == float_arg:
                _, previous, alternate = nearby[at - 1]
                if previous == alternate and (call := _CALL.fullmatch(previous)):
                    consumers.add(call[1])
            if (left, right) == word:
                call = next((m[1] for _, op, alternate in nearby[at + 1:at + 8]
                             if op == alternate and (m := _CALL.fullmatch(op))), None)
                if call:
                    consumers.add(call)
        if len(consumers) >= 2 and any((left, right) == float_arg for _, left, right in nearby):
            return [(old, consumers)]
    return []


def _witnesses(rows):
    signed, donors, argument_samples = Counter(), set(), {}
    for index in range(1, len(rows) - 14):
        callee = _CALL.fullmatch(rows[index][1])
        a1 = _selector(_A1, rows[index - 1][1], '$a1')
        a2 = _selector(_A2, rows[index + 1][1], '$a2')
        if not callee or None in (a1, a2) or any(left != right for _, left, right in rows[index - 1:index + 2]):
            continue
        call = callee[1], a1, a2
        for register, consumers in _outgoing_sample(rows, index):
            key = (*call, register)
            argument_samples.setdefault(key, []).append(consumers)
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
    return signed, donors, argument_samples


def _call(match):
    return match['callee'], integer(match['a1']), integer(match['a2'])


def variants(source, name, rows, *, header=''):
    signed, donors, argument_samples = _witnesses(rows)
    visible = _visible(source, name, header) if (signed or argument_samples) and donors else None
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
            for changed in _sample_edits(source, part, flow, declarations, holder, match['callee'],
                                         reg, argument_samples, macros):
                if (CALL_AXIS, changed) not in proposals:
                    proposals.append((CALL_AXIS, changed))
                if len(proposals) == 4:
                    return proposals
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



def _sample_edits(source, part, flow, declarations, holder, callee, register, witnesses, macros):
    for hit in _CALL_SAMPLE.finditer(part.clean, part.opening + 1, part.end):
        if hit['callee'] != callee or len(groups := witnesses.get((*_call(hit), register), ())) != 1:
            continue
        sample = hit['copy']
        if (holder in (sample, hit['axis']) or sample not in flow.names
                or macros & set(re.findall(IDENT, hit[0])) or not flow.dead(holder, hit.start('copy'))
                or not _in_scope(part, declarations[holder].start(), hit.start('copy'))):
            continue
        spans = [m.span() for m in re.finditer(rf'\b{sample}\b', part.clean, re.M)
                 if part.opening < m.start() < part.end and m.start() != declarations[sample].start('name')]
        if not 3 <= len(spans) <= 6 or spans[0] != hit.span('copy'):
            continue
        last = spans[-1][1]
        region = part.clean[hit.start():last]
        # No label can enter after the assignment. The new holder is never reset
        # or read for another purpose before the last sampled argument.
        if (re.search(rf'\b(?:goto|case|default|{holder})\b|(?m:^[ \t]*{IDENT}\s*:)', region)
                or not _in_scope(part, declarations[holder].start(), last)):
            continue
        reads = {}
        for call in _ARGUMENT_CONSUMER.finditer(part.clean, hit.end(), min(last + 120, part.end)):
            if call[1] not in groups[0] or call[1] in macros:
                continue
            for arg in re.finditer(rf'(?:^|,)\s*(?P<value>{sample})\s*(?=,|$)', call[2]):
                bare = (call.start(2) + arg.start('value'), call.start(2) + arg.end('value'))
                reads[bare] = call[1]
        if not set(spans[1:]) <= reads.keys() or not groups[0] <= {reads[span] for span in spans[1:]}:
            continue
        yield edit(source, [(start, end, holder) for start, end in spans])


ARMS = 'signed_quadratic_arm_squares'
_ARM_SOURCE = re.compile(
    rf'(?m)^(?P<binding>[ \t]*(?P<temporary>{IDENT})\s*=\s*(?P<axis>{IDENT})\s*\*\s*(?P=axis)\s*;[ \t]*\n)'
    rf'[ \t]*if\s*\(\s*(?P=axis)\s*>\s*0\.0[fF]\s*\)\s*\{{\s*'
    rf'(?P=axis)\s*=\s*\(\s*(?P<positive_square>(?P=temporary))\s*\*\s*(?P<positive>{_LITERAL})\s*\)'
    rf'\s*\+\s*(?P<bias>{_LITERAL})\s*;\s*\}}\s*else\s*\{{\s*'
    rf'(?P=axis)\s*=\s*\(\s*(?P<negative_square>(?P=temporary))\s*\*\s*\(\s*-(?P<negative>{_LITERAL})'
    rf'\s*\)\s*\)\s*-\s*(?P=bias)\s*;\s*\}}'
)
_ARM_COMPARE = re.compile(rf'c\.lt\.s \$f0, ({_SAVED})')


def _arm_witnesses(rows):
    for index, (_, left, right) in enumerate(rows):
        test = _ARM_COMPARE.fullmatch(left)
        if not test or left != right or index + 26 > len(rows):
            continue
        window = rows[index:index + 26]
        target = [op for _, op, _ in window]
        axis = test[1]
        if (not target[3].startswith('bc1f ') or not target[14].startswith('j ')
                or target[4] != f'mul.s $f0, {axis}, {axis}' or target[15] != f'add.s {axis}, $f0, $f2'
                or target[25] != f'sub.s {axis}, $f0, $f2' or target[1:3] != ['nop', 'nop']):
            continue
        if any(target[i:i + 3] != ['mtc1 $at, $f2', 'nop', 'mul.s $f0, $f0, $f2'] for i in (7, 18)):
            continue
        if any(target[i:i + 2] != ['mtc1 $at, $f2', 'nop'] for i in (12, 23)):
            continue
        altered = target.copy()
        altered[4] = f'mul.s $f2, {axis}, {axis}'
        for i in (7, 18):
            altered[i] = 'mtc1 $at, $f0'
            altered[i + 2] = 'mul.s $f0, $f2, $f0'
        if altered != [op for _, _, op in window]:
            continue
        words = [(_LUI.fullmatch(target[i]), _ORI.fullmatch(target[i + 1])) for i in (5, 10, 16, 21)]
        if all(hi and lo for hi, lo in words):
            positive, bias, negative, other_bias = (integer(hi[1]) << 16 | integer(lo[1]) for hi, lo in words)
            if bias == other_bias:
                yield positive, negative, bias


def arm_variants(source, name, rows, *, header=''):
    witnessed = set(_arm_witnesses(rows))
    visible = _visible(source, name, header) if witnessed else None
    if not visible:
        return []
    part, context = visible
    typedefs = re.findall(r'\btypedef\s+([^;{}]+?)\s+f32\s*;', context)
    if any(alias.strip() != 'float' for alias in typedefs):
        return []
    floats = _typed_locals(part, r'(?:f32|float)')
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    alternatives = []
    for hit in _ARM_SOURCE.finditer(part.clean, part.opening + 1, part.end):
        axis, temporary = hit['axis'], hit['temporary']
        before = part.clean[part.opening + 1:hit.start()].rstrip()
        key = _bits(hit['positive']), _bits('-' + hit['negative']), _bits(hit['bias'])
        if (key not in witnessed or axis == temporary or (before and before[-1] not in ';{}:')
                or macros & set(re.findall(IDENT, hit[0]))
                or len(re.findall(rf'\b{temporary}\b', part.body)) != 4
                or any(local not in floats or floats[local][0] in macros
                       or not _in_scope(part, floats[local][1], hit.start()) for local in (axis, temporary))):
            continue
        # The squared temporary has exactly two reads under the mutually exclusive arms.
        inline = f'({axis} * {axis})'
        changes = [(*hit.span('binding'), ''), (*hit.span('positive_square'), inline), (*hit.span('negative_square'), inline)]
        alternatives.append((key, changes))
        if len(alternatives) == 4:
            break
    proposals = [(ARMS, edit(source, changes)) for _, changes in alternatives]
    # Each selected branch pair has independent instruction witnesses.
    if len(alternatives) > 1 and len({key for key, _ in alternatives}) == len(alternatives):
        combined = edit(source, [change for _, changes in alternatives for change in changes])
        return [(ARMS, combined), *proposals[:3]]
    return proposals
