"""Use a witnessed saved float holder for a store and two call products."""

import re
import struct

from .clamp_return_local import _field
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .local_flow import Flow
from .operand_lifetime_repairs import _in_scope, _typed_locals, _visible
from .trig_axis_reuse import _CALL, _DECL, _SAVED, _STORE

FAMILY = 'saved_projection_gain_reuse'
_LITERAL = r'\d+\.\d+[fF]'
_FIELD = r'\*[^;={}\n]+?'
_SOURCE = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<field>{_FIELD})\s*=\s*(?P<gain>{_LITERAL})\s*;\s*'
    rf'(?P<x>{IDENT})\s*=\s*(?P<first>{IDENT})\([^;{{}}\n]+\)\s*\*\s*(?P=gain)\s*;\s*'
    rf'(?P<y>{IDENT})\s*=\s*(?P<second>{IDENT})\([^;{{}}\n]+\)\s*\*\s*(?P=gain)\s*;'
)
_DONOR = re.compile(
    rf'(?m)^[ \t]*(?P<holder>{IDENT})\s*=\s*(?P<gain>{_LITERAL})\s*;\s*'
    rf'(?:{IDENT}:\s*)?(?P<field>{_FIELD})\s*=\s*(?P=holder)\s*;\s*'
    rf'{IDENT}\s*=\s*(?P=holder)\s*\*\s*(?P<first>{IDENT})\([^;{{}}\n]+\)\s*;\s*'
    rf'(?P=holder)\s*=\s*(?P=holder)\s*\*\s*(?P<second>{IDENT})\([^;{{}}\n]+\)\s*;'
)
_HIGH = re.compile(rf'lui \$at, ({NUMBER})')
_LOW = re.compile(rf'ori \$at, \$at, ({NUMBER})')
_MOVE = re.compile(rf'mtc1 \$at, ({_SAVED})')


def _sequence(code, index, *, donor):
    window = code[index:index + 17]
    if len(window) < 9:
        return None
    high, low, move, store = (_HIGH.fullmatch(window[0]), _LOW.fullmatch(window[1]),
                             _MOVE.fullmatch(window[2]), _STORE.fullmatch(window[4]))
    if not (high and low and move and window[3] == 'nop' and store and move[1] == store[1]):
        return None
    register = move[1]
    calls = [(offset, match[1]) for offset, op in enumerate(window[5:], 5) if (match := _CALL.fullmatch(op))]
    if len(calls) < 2 or calls[0][0] != 5:
        return None
    (first, a), (second, b) = calls[:2]
    if a == b:
        return None
    before = f'mul.s $f0, {register}, $f0' if donor else f'mul.s $f0, $f0, {register}'
    after = f'mul.s {register}, {register}, $f0' if donor else before
    stop = calls[2][0] if len(calls) > 2 else len(window)
    if before not in window[first + 1:second] or after not in window[second + 1:stop]:
        return None
    return (integer(high[1]) << 16 | integer(low[1]), store[2], a, b), register


def _witnesses(rows):
    left = [target for _, target, _ in rows]
    right = [candidate for _, _, candidate in rows]
    needed, proven = set(), set()
    for index, op in enumerate(left):
        if not op.startswith('lui $at, ') or right[index] != op:
            continue
        target = _sequence(left, index, donor=False)
        if target:
            candidate = _sequence(right, index, donor=False)
            if candidate and candidate[0] == target[0] and candidate[1] != target[1]:
                needed.add(target)
        donor = _sequence(left, index, donor=True)
        if donor and _sequence(right, index, donor=True) == donor:
            proven.add(donor)
    return {(bits, integer(offset), first, second) for (bits, offset, first, second), _ in needed & proven}


def _key(match, prefix):
    field = _field(match['field'], prefix)
    if not field:
        return None
    try:
        bits = int.from_bytes(struct.pack('>f', float(match['gain'][:-1])), 'big')
    except (ValueError, OverflowError):
        return None
    return bits, field[1], match['first'], match['second']


def variants(source, name, rows, *, header=''):
    evidence = _witnesses(rows)
    visible = _visible(source, name, header) if evidence else None
    if not visible:
        return []
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
    prefix = part.clean[:part.opening]
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    donors = [(m, key) for m in _DONOR.finditer(part.clean, part.opening + 1, part.end)
              if (key := _key(m, prefix)) in evidence and not macros & set(re.findall(IDENT, m[0]))]
    proposals = []
    for m in _SOURCE.finditer(part.clean, part.opening + 1, part.end):
        key = _key(m, prefix)
        if key not in evidence or macros & set(re.findall(IDENT, m[0])):
            continue
        before = part.clean[part.opening + 1:m.start()].rstrip()
        if before and before[-1] not in ';{}:':
            continue
        gain_uses = list(re.finditer(rf'(?<![\w.]){re.escape(m["gain"])}\b', m[0]))
        if len(gain_uses) != 3:
            continue
        for donor, donor_key in donors:
            holder = donor['holder']
            if (key != donor_key or holder not in flow.names or re.search(rf'\b{holder}\b', m[0])
                    or ordinary[holder][0] in macros
                    or not _in_scope(part, declarations[holder].start(), m.start())
                    or not flow.dead(holder, m.start('field'))):
                continue
            changes = [(m.start() + use.start(), m.start() + use.end(), holder) for use in gain_uses]
            at = m.start()
            changes.append((at, at, f'{m["indent"]}{holder} = {m["gain"]};\n'))
            changed = (FAMILY, edit(source, changes))
            if changed not in proposals:
                proposals.append(changed)
            if len(proposals) == 4:
                return proposals
    return proposals
