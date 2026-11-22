"""Stage a float sample before reading the old smoothing field."""

import re
import struct
from itertools import islice

from .clamp_return_local import _field
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .operand_lifetime_repairs import _escaped, _in_scope, _typed_locals, _visible
from .pattern_repairs import close
from .pointer_pair_repairs import declarations

FAMILY = 'smoothing_call_before_read'
RECORD = 'record_read_after_projection'
_FPR = r'\$f(?:[12]?[0-9]|3[01])'
_SAVED = r'\$f(?:20|22|24|26|28|30)'
_CALL = re.compile(rf'jal ({IDENT})')
_MUL = re.compile(rf'mul\.s ({_SAVED}), \$f0, ({_FPR})')
_LOAD = re.compile(rf'lwc1 ({_FPR}), ({NUMBER})(\(\$\w+\))')
_LUI = re.compile(rf'lui \$at, ({NUMBER})')
_ORI = re.compile(rf'ori \$at, \$at, ({NUMBER})')
_LITERAL = r'\d+\.\d+[fF]'
_ARG = rf'(?:{IDENT}|-?{NUMBER})'
_SOURCE = re.compile(
    rf'(?m)^(?P<pad>[ \t]*)(?P<old>{IDENT})\s*=\s*(?P<field>\*[^;={{}}\n]+?)\s*;\s*'
    rf'(?P<result>{IDENT})\s*=\s*\(\(\s*(?P<multiply>\(\s*(?P<expr>(?P<call>{IDENT})\(\s*'
    rf'(?:{_ARG}\s*(?:,\s*{_ARG}\s*)*)?\)\s*\*\s*(?P<scale>{_LITERAL}))\s*\))'
    rf'\s*-\s*(?P=old)\)\s*\*\s*{_LITERAL}\)\s*\+\s*(?P=old)\s*;\s*'
    rf'(?P=field)\s*=\s*(?P=result)\s*;\s*if\s*\(\s*(?P=result)\s*<\s*\(-{_LITERAL}\)\s*\)'
)

_PROJECTION_RECORD = re.compile(
    rf'(?m)^(?P<capture>(?P<pad>[ \t]*)(?P<record>{IDENT})\s*=\s*'
    rf'\*\(\s*\(\s*void\s*\*\s*\*\s*\)\s*\(\s*\(\s*\(\s*char\s*\*\s*\)'
    rf'\s*(?P<base>{IDENT})\s*\)\s*\+\s*(?P<offset>{NUMBER})\s*\)\s*\)\s*;[ \t]*\n)'
    rf'(?P<projection>(?P=pad)(?P<acc>{IDENT})\s*\+=\s*{IDENT}\s*\*\s*(?P<call>{IDENT})'
    rf'\((?P<arguments>[^;{{}}\n]+)\)\s*;[ \t]*\n)'
    rf'(?P=pad)if\s*\('
)
_POINTER_LOAD = re.compile(rf'lw (\$\w+), ({NUMBER})\((\$\w+)\)')
_FLAG_LOAD = re.compile(rf'lhu (\$\w+), ({NUMBER})\((\$\w+)\)')
_CALLER = re.compile(r'\$a[0-3]')
_CALLEE = re.compile(r'\$s[0-7]|\$fp')


def _record_evidence(rows):
    targets = [(i, left) for i, (_, left, _) in enumerate(rows) if left]
    witnesses = set()
    for j in range(4, len(targets) - 5):
        index, op = targets[j]
        pointer = _POINTER_LOAD.fullmatch(op)
        if not pointer or not _CALLER.fullmatch(pointer[1]) or rows[index][2]:
            continue
        multiply = re.fullmatch(rf'mul\.s \$f0, {_SAVED}, \$f0', targets[j - 1][1])
        call_index, call_line = targets[j - 4]
        call = _CALL.fullmatch(call_line)
        if not multiply or not call or rows[call_index][2] != call_line:
            continue
        region = targets[j + 1:j + 6]
        flag = next(((row, m) for row, line in region[:3] if (m := _FLAG_LOAD.fullmatch(line))
                     and m[3] == pointer[1]), None)
        if not flag:
            continue
        flag_index, load = flag
        mask = next((m for row, line in region if row > flag_index
                     and (m := re.fullmatch(rf'andi {re.escape(load[1])}, {re.escape(load[1])}, ({NUMBER})', line))
                     and rows[row][2] == line), None)
        if not mask:
            continue
        before = [right for _, _, right in rows[targets[max(0, j - 8)][0]:call_index] if right]
        for entry in before:
            early = _POINTER_LOAD.fullmatch(entry)
            if not early or not _CALLEE.fullmatch(early[1]) or early.groups()[1:] != pointer.groups()[1:]:
                continue
            if rows[flag_index][2] == f'lhu {load[1]}, {load[2]}({early[1]})':
                witnesses.add((call[1], integer(pointer[2]), integer(load[2]), integer(mask[1])))
    return witnesses


def _record_proposals(source, part, context, macros, witnesses):
    available = {m['name']: m for m in declarations(part, nested=True)}
    floats = _typed_locals(part, r'(?:f32|float)')
    if re.search(r'\btypedef\b[^;\n]*\b(?:volatile|_Atomic)\b[^;\n]*\bu16\s*;', context):
        return
    for m in _PROJECTION_RECORD.finditer(part.clean, part.opening + 1, part.end):
        record, base, call, acc = m['record'], m['base'], m['call'], m['acc']
        arguments = set(re.findall(IDENT, m['arguments']))
        if (record not in available or not _in_scope(part, available[record].start(), m.start())
                or acc not in floats or not _in_scope(part, floats[acc][1], m.start())
                or record == base or record in arguments or base not in arguments
                or _escaped(part.body, base) or re.search(r'=|\+\+|--', m['arguments'])
                or not re.search(rf'\b(?:f32|float)\s+{call}\s*\(', context)):
            continue
        end = close(part.clean, m.end() - 1)
        if not end or re.search(r'/[*/]|#', source[m.start():end]):
            continue
        if macros & set(re.findall(IDENT, part.clean[m.start():end])):
            continue
        prefix = part.clean[part.opening + 1:m.start()].rstrip()
        if prefix and prefix[-1] not in ';{}:':
            continue
        condition = part.clean[m.end():end]
        flag = re.search(
            rf'\*\s*\(\s*\(\s*(?:u16|unsigned\s+short)\s*\*\s*\)\s*'
            rf'\(\s*\(\s*\(\s*char\s*\*\s*\)\s*{record}\s*\)\s*\+\s*({NUMBER})'
            rf'\s*\)\s*\)\s*\)*\s*&\s*({NUMBER})',
            condition,
        )
        if (flag and not re.search(r'[^\s(!]', condition[:flag.start()])
                and (call, integer(m['offset']), integer(flag[1]), integer(flag[2])) in witnesses):
            yield RECORD, edit(source, [(m.start(), m.end('projection'),
                                        source[slice(*m.span('projection'))] + source[slice(*m.span('capture'))])])


def _evidence(rows):
    target = [(i, left) for i, (_, left, _) in enumerate(rows) if left]
    witnesses = set()
    for j in range(6, len(target) - 2):
        _, op = target[j]
        mul = _MUL.fullmatch(op)
        load = _LOAD.fullmatch(target[j + 1][1])
        if not mul or not load or target[j + 2][1] != f'sub.s $f2, {mul[1]}, {load[1]}':
            continue
        before = [line for _, line in target[j - 6:j]]
        call = _CALL.fullmatch(before[0])
        upper = _LUI.fullmatch(before[2])
        lower = _ORI.fullmatch(before[3])
        if not call or not upper or not lower or before[4:] != [f'mtc1 $at, {mul[2]}', 'nop']:
            continue
        candidates = [right for _, _, right in rows[max(0, target[j - 6][0] - 1):target[j + 2][0] + 1] if right]
        call_at = next((i for i, line in enumerate(candidates) if line == before[0]), None)
        if call_at is None or any(
            match and match.groups()[1:] == load.groups()[1:]
            for match in map(_LOAD.fullmatch, candidates[call_at + 1:])
        ):
            continue
        if any(
            match and match.groups()[1:] == load.groups()[1:]
            for match in map(_LOAD.fullmatch, candidates[:call_at])
        ):
            witnesses.add((call[1], integer(load[2]), (integer(upper[1]) << 16) | integer(lower[1])))
    return witnesses


def variants(source, name, rows, *, header=''):
    witnesses = _evidence(rows)
    records = _record_evidence(rows)
    visible = _visible(source, name, header) if witnesses or records else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\btypedef\b[^;\n]*\b(?:volatile|_Atomic)\b[^;\n]*\bf32\s*;', context):
        return []
    available = _typed_locals(part, r'(?:f32|float)')
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    proposals = []
    for m in _SOURCE.finditer(part.clean, part.opening + 1, part.end):
        result, old = m['result'], m['old']
        field = _field(m['field'], part.clean[:part.opening])
        if not field or result in (old, field[0]):
            continue
        if not re.search(rf'\b(?:f32|float)\s+{m["call"]}\s*\(', context):
            continue
        if any(local not in available or not _in_scope(part, available[local][1], m.start())
               or _escaped(part.body, local) for local in (result, old)):
            continue
        if any(re.search(rf'\b(?:volatile|_Atomic)\b[^;{{}}\n]*\b{local}\b', context)
               for local in (result, old, field[0])):
            continue
        if old in re.findall(IDENT, m['expr']) or macros & set(re.findall(IDENT, m[0])):
            continue
        if re.search(r'/[*/]|#', source[m.start():m.end()]):
            continue
        before = part.clean[part.opening + 1:m.start()].rstrip()
        if before and before[-1] not in ';{}:':
            continue
        try:
            bits = struct.unpack('>I', struct.pack('>f', float(m['scale'][:-1])))[0]
        except OverflowError:
            continue
        if (m['call'], field[1], bits) not in witnesses:
            continue
        expression = source[slice(*m.span('expr'))]
        intro = f'{m["pad"]}{result} = {expression};\n'
        proposals.append((FAMILY, edit(source, [(m.start(), m.start(), intro), (*m.span('multiply'), result)])))
        if len(proposals) == 4:
            break
    if records and len(proposals) < 4:
        proposals.extend(islice(_record_proposals(source, part, context, macros, records), 4 - len(proposals)))
    return proposals
