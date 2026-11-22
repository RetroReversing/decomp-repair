"""Stage a projection scale in its exhausted saved local and balance a predicate delay slot."""

import re
import struct

from .balanced_float_predicate_return import _PREDICATES, _bits, _earlier
from .clamp_return_local import _field
from .compiler_phase_repairs import fresh
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .local_flow import Flow
from .operand_lifetime_repairs import _in_scope, _typed_locals, _visible

FAMILY = 'balanced_projection_scale'
_SAVED = r'\$f(?:20|22|24|26|28|30)'
_FLOAT_DECL = re.compile(rf'\b(?:f32|float)\s+(?P<name>{IDENT})\s*;')
_FPR = r'\$f(?:[12]?[0-9]|3[01])'
_PROJECTION = re.compile(
    rf'(?m)^[ \t]*(?P<holder>{IDENT})\s*=\s*\*[^;{{}}\n]+;\s*'
    rf'(?P<acc1>{IDENT})\s*\+=\s*\(\s*(?P=holder)\s*\*\s*{IDENT}\([^;{{}}\n]+\)\s*\);\s*'
    rf'(?P<acc2>{IDENT})\s*\+=\s*\(\s*(?P=holder)\s*\*\s*(?P<call>{IDENT})\([^;{{}}\n]+\)\s*\);\n'
    rf'(?P<pad>[ \t]*)(?P<old>{IDENT})\s*=\s*(?P<load>\*[^;{{}}\n]+);\s*'
    rf'(?P<result>{IDENT})\s*=\s*(?P<formula>\(\(\((?P<scale>(?P<value>{IDENT})\s*\*\s*'
    rf'(?P<factor>\d+\.\d+[fF]))\)\s*-\s*(?P=old)\)\s*\*\s*\d+\.\d+[fF]\)\s*\+\s*(?P=old))\s*;\s*'
    rf'(?P<store>\*[^;={{}}\n]+)\s*=\s*(?P=formula)\s*;'
)


def _float_bits(literal):
    try:
        return struct.unpack('>I', struct.pack('>f', float(literal[:-1])))[0]
    except OverflowError:
        return None


def _late(rows, target):
    for i in range(8, len(target) - 2):
        index, op = target[i]
        scale = re.fullmatch(rf'mul\.s ({_SAVED}), ({_SAVED}), ({_FPR})', op)
        load = re.fullmatch(rf'lwc1 ({_FPR}), ({NUMBER})\(\$\w+\)', target[i + 1][1])
        call = re.fullmatch(rf'jal ({IDENT})', target[i - 8][1])
        if not (scale and load and call):
            continue
        holder, value, bound = scale.groups()
        product = f'mul.s $f0, {holder}, $f0'
        if holder == value or target[i - 5][1] != product:
            continue
        bits = _bits(target, i, bound)
        sub = re.fullmatch(rf'sub\.s ({_FPR}), {re.escape(holder)}, {re.escape(load[1])}', target[i + 2][1])
        if not bits or bits & 0x80000000 or not sub:
            continue
        scratch = sub[1]
        if (rows[index][2] != f'mul.s {scratch}, {value}, {bound}'
                or rows[target[i + 1][0]][2] != load[0]):
            continue
        end = target[i + 2][0]
        candidate = [right for _, _, right in rows[index:end + 1] if right]
        if candidate[-2:] == [product, f'sub.s {scratch}, {scratch}, {load[1]}']:
            yield index, call[1], bits, integer(load[2])


def variants(source, name, rows, *, header=''):
    target = [(i, left) for i, (_, left, _) in enumerate(rows) if left]
    early = list(_earlier(rows, target, same_comparisons=False))
    late = list(_late(rows, target))
    witnesses = {(bound, call, bits, offset) for start, _, bound in early
                 for finish, call, bits, offset in late if start < finish}
    visible = _visible(source, name, header) if witnesses else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\btypedef\b[^;\n]*\b(?:volatile|_Atomic)\b[^;\n]*\bf32\s*;', context):
        return []
    floats = _typed_locals(part, r'(?:f32|float)')
    ints = _typed_locals(part, r'(?:s32|int)')
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    declarations = [m for m in _FLOAT_DECL.finditer(part.clean, part.opening + 1, part.end)
                    if m['name'] in floats and m.start() == floats[m['name']][1]]
    try:
        flow = Flow(part, declarations)
    except (ValueError, RecursionError):
        return []
    guards = list(_PREDICATES.finditer(part.clean, part.opening + 1, part.end))
    flag = fresh(source, header, 'repair_guard_fold_bits')
    proposals = []
    for match in _PROJECTION.finditer(part.clean, part.opening + 1, part.end):
        holder, value, old, result = (match[key] for key in ('holder', 'value', 'old', 'result'))
        if len({holder, value, old, result, match['acc1'], match['acc2']}) != 6:
            continue
        prefix = part.clean[:part.opening]
        field = _field(match['load'], prefix)
        if not field or field != _field(match['store'], prefix):
            continue
        if not all(local in floats and _in_scope(part, floats[local][1], match.start())
                   for local in (holder, value, old, result)):
            continue
        if macros & set(re.findall(IDENT, match[0])) or holder not in flow.names:
            continue
        if not flow.dead(holder, match.start('old')):
            continue
        factor = _float_bits(match['factor'])
        for guard in reversed(guards):
            first, second = guard['first'], guard['second']
            if guard.end() >= match.start() or first == second:
                continue
            if not all(local in ints and _in_scope(part, ints[local][1], guard.start())
                       for local in (first, second)):
                continue
            if macros & set(re.findall(IDENT, guard[0])):
                continue
            if (_float_bits(guard['limit']), match['call'], factor, field[1]) not in witnesses:
                continue
            if any(re.search(rf'\b(?:volatile|_Atomic)\b[^;{{}}\n]*\b{local}\b', context)
                   for local in (holder, value, old, result, first, second)):
                continue
            position = ints[first][1]
            indent = source[source.rfind('\n', 0, position) + 1:position]
            if indent.strip():
                continue
            scale = '(' + match['scale'] + ')'
            formula = match['formula'].replace(scale, holder, 1)
            store_at = part.clean.index(match['formula'], match.end('store'), match.end())
            edits = [(position, position, f'{ints[first][0]} {flag};\n{indent}'),
                     (guard.start('pad'), guard.start('pad'), f'{guard["pad"]}{flag} = {first} ^ 1;\n'),
                     (*guard.span('inverted'), flag),
                     (match.start('pad'), match.start('pad'), f'{match["pad"]}{holder} = {match["scale"]};\n'),
                     (*match.span('formula'), formula),
                     (store_at, store_at + len(match['formula']), formula)]
            proposals.append((FAMILY, edit(source, edits)))
            if len(proposals) == 4:
                return proposals
    return proposals
