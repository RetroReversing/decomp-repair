"""Share the selected float and final projection result when their lifetimes permit it."""

import re
import struct

from .clamp_return_local import _field
from .integer_repair_support import IDENT, NUMBER, edit, integer, refs
from .local_flow import Flow
from .operand_lifetime_repairs import _in_scope, _typed_locals, _visible

FAMILY = 'shared_projection_lifetime'
_SAVED = r'\$f(?:20|22|24|26|28|30)'
_GPR = r'\$\w+'
_LUI = re.compile(rf'lui \$at, ({NUMBER})')
_ORI = re.compile(rf'ori \$at, \$at, ({NUMBER})')
_STORE = re.compile(rf'swc1 ({_SAVED}), ({NUMBER})(\(\$\w+\))')
_CALL = re.compile(rf'jal ({IDENT})')
_BRANCH = re.compile(rf'bnez {_GPR}, (0x[0-9a-f]+)(?: \[bytes [0-9a-f]+\])?')
_MOVE = re.compile(rf'mov\.s ({_SAVED}), (\$f\d+)')
_DEFINITION = re.compile(rf'\b(?P<type>f32|float)\s+(?P<name>{IDENT})\s*;')
_SOURCE = re.compile(
    rf'(?m)^[ \t]*(?P<seed>{IDENT})\s*=\s*(?P<literal>\d+\.\d+[fF])\s*;\s*'
    rf'(?P<label>{IDENT})\s*:\s*(?P<field>\*[^;={{}}\n]+?)\s*=\s*(?P=seed)\s*;\s*'
    rf'{IDENT}\s*=\s*(?P=seed)\s*\*\s*(?P<first>{IDENT})\([^;{{}}\n]+\)\s*;\s*'
    rf'(?P<result>{IDENT})\s*=\s*(?P=seed)\s*\*\s*(?P<second>{IDENT})\([^;{{}}\n]+\)\s*;'
)


def _predecessor(rows, index, wanted, previous):
    for j in range(index + 1, len(rows) - 1):
        branch = _BRANCH.fullmatch(rows[j][0])
        move = _MOVE.fullmatch(rows[j + 1][0])
        other = _MOVE.fullmatch(rows[j + 1][1])
        if not branch or integer(branch[1]) != 4 * index or not move or not other:
            continue
        if move[1] != wanted or other[1] != previous:
            continue
        before = [left for left, _ in rows[max(0, j - 64):j]]
        if f'mtc1 $zero, {move[2]}' in before:
            return True
    return False


def _witnesses(rows):
    code = [(left, right) for _, left, right in rows if left]
    evidence = set()
    for j in range(4, len(code) - 8):
        left, right = code[j]
        store, candidate = _STORE.fullmatch(left), _STORE.fullmatch(right)
        if not store or not candidate or store[1] == candidate[1] or store.groups()[1:] != candidate.groups()[1:]:
            continue
        preferred, prior = store[1], candidate[1]
        hi, lo, move, nop = [op for op, _ in code[j - 4:j]]
        upper, lower = _LUI.fullmatch(hi), _ORI.fullmatch(lo)
        if not upper or not lower or (move, nop) != (f'mtc1 $at, {preferred}', 'nop'):
            continue
        first = _CALL.fullmatch(code[j + 1][0])
        next_call = next((k for k in range(j + 2, j + 8) if _CALL.fullmatch(code[k][0])), None)
        if not first or next_call is None or next_call + 1 >= len(code):
            continue
        second = _CALL.fullmatch(code[next_call][0])
        if first[1] == second[1]:
            continue
        if (f'mul.s $f0, {preferred}, $f0', f'mul.s $f0, {prior}, $f0') not in code[j + 2:next_call]:
            continue
        last = (f'mul.s {preferred}, {preferred}, $f0', f'mul.s {preferred}, {prior}, $f0')
        if last in code[next_call + 1:next_call + 10] and _predecessor(code, j, preferred, prior):
            evidence.add((integer(store[2]), (integer(upper[1]) << 16) | integer(lower[1]), first[1], second[1]))
    return evidence


def _separate_except_final_projection(flow, seed, result, sink):
    for node in flow.nodes:
        if not {seed, result} <= (node.live | node.defines):
            continue
        if node is not sink or result not in node.defines or result in node.live:
            return False
        if any(seed in flow.nodes[successor].live for successor in node.successors):
            return False
    return True


def variants(source, name, rows, *, header=''):
    evidence = _witnesses(rows)
    visible = _visible(source, name, header) if evidence else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\btypedef\b[^;\n]*\b(?:volatile|_Atomic)\b[^;\n]*\bf32\s*;', context):
        return []
    ordinary = _typed_locals(part, r'(?:f32|float)')
    declarations = {m['name']: m for m in _DEFINITION.finditer(part.clean, part.opening + 1, part.end)
                    if m['name'] in ordinary and m.start() == ordinary[m['name']][1]}
    try:
        flow = Flow(part, declarations.values())
    except (ValueError, RecursionError):
        return []
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    proposals = []
    for m in _SOURCE.finditer(part.clean, part.opening + 1, part.end):
        seed, result = m['seed'], m['result']
        if (seed == result or seed not in flow.names or result not in flow.names
                or macros & set(re.findall(IDENT, m[0]))
                or re.search(r'/[*/]|#', source[m.start():m.end()])):
            continue
        field = _field(m['field'], part.clean[:part.opening])
        if not field or field[0] in (seed, result):
            continue
        try:
            bits = struct.unpack('>I', struct.pack('>f', float(m['literal'][:-1])))[0]
        except OverflowError:
            continue
        if (field[1], bits, m['first'], m['second']) not in evidence:
            continue
        references = refs(part, declarations[seed])
        if len(references) != 5 or not all(_in_scope(part, declarations[result].start(), use.start()) for use in references):
            continue
        alternative = next((use for use in references if use.start() >= m.end()), None)
        if not alternative or not re.match(r'\s*=\s*0\.0[fF]\s*;', part.clean[alternative.end():]):
            continue
        suffix = part.clean[alternative.end():part.end]
        if not re.search(rf'\bgoto\s+{m["label"]}\s*;', suffix):
            continue
        sink = flow.at(m.start('result'))
        if not sink or not _separate_except_final_projection(flow, seed, result, sink):
            continue
        proposals.append((FAMILY, edit(source, [(use.start(), use.end(), result) for use in references])))
        if len(proposals) == 4:
            break
    return proposals
