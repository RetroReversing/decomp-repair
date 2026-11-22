"""Pair target clamp input scheduling with later first-flag stages."""

import re
import struct
from itertools import combinations

from .balanced_float_predicate_return import _PREDICATES
from .clamp_return_local import _field
from .compiler_phase_repairs import fresh
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .operand_lifetime_repairs import _escaped, _in_scope, _typed_locals, _visible

FAMILY = 'balanced_clamp_predicates'
_FPR = r'\$f(?:[12]?[0-9]|3[01])'
_LUI = re.compile(rf'lui \$at, ({NUMBER})')
_ORI = re.compile(rf'ori \$at, \$at, ({NUMBER})')
_LOAD = re.compile(rf'lwc1 ({_FPR}), ({NUMBER})(\(\$\w+\))')
_COMPARE = re.compile(rf'c\.le\.s ({_FPR}), ({_FPR})')
_LITERAL = r'\d+\.\d+[fF]'
_FIELD = r'\*[^;={}\n]+?'
_CLAMP = re.compile(
    rf'(?m)^[ \t]*(?P<value>{IDENT})\s*=\s*(?P<load>{_FIELD})\s*;\s*'
    rf'^(?P<pad>[ \t]*)(?P<bound>{IDENT})\s*=\s*-(?P<limit>{_LITERAL})\s*;\s*'
    r'if\s*\(\(\s*(?P=value)\s*<\s*\(-(?P=limit)\)\s*\)\s*\|\|'
    r'\s*\(\(\s*(?P=bound)\s*=\s*(?P=limit)\s*,\s*(?P=value)\s*>\s*(?P=limit)\s*\)\s*\)\s*\)\s*'
    rf'\{{\s*(?P<store>{_FIELD})\s*=\s*(?P=bound)\s*;\s*\}}'
)


def _bits(literal):
    try:
        return struct.unpack('>I', struct.pack('>f', float(literal[:-1])))[0]
    except OverflowError:
        return None


def _constant(target, at, register):
    escaped = re.escape(register)
    for i in range(at - 1, max(1, at - 90), -1):
        _, line = target[i]
        if line == f'mtc1 $at, {register}':
            high, low = _LUI.fullmatch(target[i - 2][1]), _ORI.fullmatch(target[i - 1][1])
            return (integer(high[1]) << 16) | integer(low[1]) if high and low else None
        if (re.match(rf'(?:l[wd]c1|\w+\.[sd]) {escaped}, ', line)
                or re.match(rf'(?:mtc1|dmtc1) \$\w+, {escaped}$', line)
                or (line.startswith('jal ') and int(register[2:]) < 20)):
            return None
    return None


def _clamp_sites(rows, target):
    sites = []
    for i in range(len(target) - 9):
        start, line = target[i]
        load = _LOAD.fullmatch(line)
        if not load:
            continue
        compare = re.fullmatch(rf'c\.lt\.s {re.escape(load[1])}, ({_FPR})', target[i + 5][1])
        high, low = _LUI.fullmatch(target[i + 1][1]), _ORI.fullmatch(target[i + 2][1])
        if not compare or not high or not low:
            continue
        group = [op for _, op in target[i:i + 10]]
        bound = compare[1]
        if (group[3:5] != [f'mtc1 $at, {bound}', 'nop'] or not group[8].startswith('bc1tl ')
                or group[9] != f'swc1 {bound}, {load[2]}{load[3]}'):
            continue
        end = target[i + 5][0]
        candidate = [right for _, _, right in rows[start:end + 1] if right]
        if candidate != [*group[1:4], group[0], group[5]]:
            continue
        bits = (integer(high[1]) << 16) | integer(low[1])
        if bits & 0x80000000:
            sites.append((i, integer(load[2]), bits ^ 0x80000000))
    return sites


def _predicate_sites(rows, target, after):
    for i in range(max(10, after + 1), len(target) - 7):
        index, op = target[i]
        low, other_low = _COMPARE.fullmatch(op), _COMPARE.fullmatch(rows[index][2])
        if not low or not other_low:
            continue
        following = [line for _, line in target[i + 1:i + 8]]
        if (following[:2] != ['addiu $v0, $zero, 1', 'nop'] or not following[2].startswith('bc1t ')
                or following[3:] != ['xori $v1, $v1, 1', 'move $v0, $zero', 'xori $v0, $v0, 1', 'or $v0, $v1, $v0']):
            continue
        nearby = [right for _, _, right in rows[index:target[i + 7][0] + 1] if right]
        if (len(nearby) < 6 or nearby[1:3] != ['nop', 'nop'] or not nearby[3].startswith('bc1t ')
                or nearby[4] != 'addiu $v0, $zero, 1'):
            continue
        negative = _constant(target, i, low[1])
        if not negative or not negative & 0x80000000:
            continue
        for j in range(i - 5, max(2, i - 14), -1):
            before, line = target[j]
            high, other_high = _COMPARE.fullmatch(line), _COMPARE.fullmatch(rows[before][2])
            if not high or high[1] != low[2] or not other_high or other_high[1] != other_low[2]:
                continue
            if _constant(target, j, high[2]) == negative ^ 0x80000000:
                yield i, negative ^ 0x80000000
                break


def _predicate_groups(predicates, size):
    """Group the same tolerance within one local sequence of comparisons."""
    for start in range(len(predicates) - size + 1):
        block = predicates[start:start + size]
        if (len({bound for _, bound in block}) == 1
                and all(right[0] - left[0] <= 40 for left, right in zip(block, block[1:]))):
            yield block[0][1]


def _clamp_edit(m):
    pad, value, limit, field = (m[key] for key in ('pad', 'value', 'limit', 'store'))
    return (f'{pad}if ({value} < (-{limit}))\n{pad}{{\n{pad}  {field} = -{limit};\n{pad}}}\n'
            f'{pad}else if ({value} > {limit})\n{pad}{{\n{pad}  {field} = {limit};\n{pad}}}')


def _clamp_sources(part, locals_, macros, sites):
    prefix = part.clean[:part.opening]
    for m in _CLAMP.finditer(part.clean, part.opening + 1, part.end):
        value, bound = m['value'], m['bound']
        if (value == bound or any(local not in locals_ or not _in_scope(part, locals_[local][1], m.start())
                                  or _escaped(part.body, local) for local in (value, bound))):
            continue
        # The temporary held only the two bounds and the shared store's value.
        if len(re.findall(rf'\b{bound}\b', part.body)) != 4 or macros & set(re.findall(IDENT, m[0])):
            continue
        field = _field(m['load'], prefix)
        if not field or field != _field(m['store'], prefix) or (field[1], _bits(m['limit'])) not in sites:
            continue
        yield m


def _source_within_limit(source, max_bytes):
    if max_bytes is None or len(source.encode()) <= max_bytes:
        return source
    # Preserve line numbers and all literal, directive and continuation spelling.
    if re.search(r'(?m)^\s*#|["\x27]|\\\r?\n', source):
        return None
    squeezed = re.sub(r'(?m)^ (?= {3})', '', source)
    return squeezed if len(squeezed.encode()) <= max_bytes else None


def variants(source, name, rows, *, header='', max_bytes=None):
    target = [(i, left) for i, (_, left, _) in enumerate(rows) if left]
    clamps = _clamp_sites(rows, target)
    if not 1 <= len(clamps) <= 4:
        return []
    after = max(index for index, _, _ in clamps)
    observed = list(_predicate_sites(rows, target, after))
    groups = {(bound, size) for size in range(1, len(clamps) + 1)
              for bound in _predicate_groups(observed, size)}
    visible = _visible(source, name, header) if groups else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\btypedef\b[^;\n]*\b(?:volatile|_Atomic)\b[^;\n]*\b(?:f32|s32)\s*;', context):
        return []
    floats = _typed_locals(part, r'(?:f32|float)')
    ints = _typed_locals(part, r'(?:s32|int)')
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    candidates = list(_clamp_sources(part, floats, macros, {(offset, bits) for _, offset, bits in clamps}))
    if len(candidates) != len(clamps):
        return []
    changes = [(m.start('pad'), m.end(), _clamp_edit(m)) for m in candidates]
    guards = {bound: [] for bound, _ in groups}
    for m in _PREDICATES.finditer(part.clean, candidates[-1].end(), part.end):
        bound = _bits(m['limit'])
        if bound in guards:
            guards[bound].append(m)
    proposals = []
    for bound, size in sorted(groups):
        if len(guards[bound]) != size:
            continue
        flag_changes = []
        for m in guards[bound]:
            first, second = m['first'], m['second']
            if (first == second or any(flag not in ints or not _in_scope(part, ints[flag][1], m.start())
                                      or _escaped(part.body, flag) for flag in (first, second))
                    or macros & set(re.findall(IDENT, m[0]))):
                break
            position = ints[first][1]
            indent = source[source.rfind('\n', 0, position) + 1:position]
            gate = re.search(rf'\(\s*{second}\s*\^\s*1\s*\)\s*\|\s*{re.escape(m["inverted"])}$',
                             part.clean[m.start():m.end('inverted')])
            if indent.strip() or not gate:
                break
            flag = fresh(source, header, f'repair_late_{first}')
            inverted = gate[0].split('|', 1)[0].rstrip()
            flag_changes.extend([
                (position, position, f'{ints[first][0]} {flag};\n{indent}'),
                (m.start('pad'), m.start('pad'), f'{m["pad"]}{flag} = {first} ^ 1;\n'),
                (m.start() + gate.start(), m.end('inverted'), f'{flag} | {inverted}'),
            ])
        else:
            for selected in combinations(changes, size):
                candidate = _source_within_limit(edit(source, [*selected, *flag_changes]), max_bytes)
                if candidate:
                    proposals.append((FAMILY, candidate))
                if len(proposals) == 4:
                    return proposals
    return proposals
