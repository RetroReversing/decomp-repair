"""Recover a float component consumed separately from two stack-buffer calls.

A decompiler may collapse the two versions of a stack output into one C
array element. Only offer a split when the target reads the component
after each call and subtracts it from the same saved accumulator.
"""

import re

from .call_lifetime_repairs import block_path
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'stack_call_output_phases'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|0|[1-9]\d*)'
FPR = r'\$f(?:[asvt]?\d+)'
SAVED = r'\$(?:fp|s[0-7])'
FLOAT_TYPE = r'(?:f32|float)'
_READ = re.compile(rf'lwc1\s+({FPR}),\s*({NUMBER})\(\$sp\)')
_SUB = re.compile(rf'sub\.s\s+({FPR}),\s*\1,\s*({FPR})')
_KEEP = re.compile(rf'mfc1\s+({SAVED}),\s*({FPR})')
_ARGUMENT = re.compile(rf'addiu\s+\$a0,\s*\$sp,\s*({NUMBER})')
_CONTROL = re.compile(r'(?:b\w*|j\w*|break|syscall)\b')
_LABEL = re.compile(r'(?m)^[ \t]*[A-Za-z_]\w*\s*:(?!:)|\b(?:case\s+[^:{}\n]+|default\s*):')
_REPEATED = re.compile(
    rf'(?m)^[ \t]*(?P<value>{IDENT})\s*=\s*\(\s*(?P<seed>0\.0[fF])\s*-\s*'
    rf'(?P<buf>{IDENT})\s*\[\s*(?P<index>{NUMBER})\s*\]\s*\)\s*-\s*'
    r'(?P=buf)\s*\[\s*(?P=index)\s*\]\s*;')


def _written_to_saved(window, offset):
    for i, row in enumerate(window):
        loaded = _READ.fullmatch(row)
        if not loaded or int(loaded[2], 0) != offset:
            continue
        for j in range(i + 1, min(i + 15, len(window))):
            subtract = _SUB.fullmatch(window[j])
            if subtract and subtract[2] == loaded[1]:
                transfers = re.compile(rf'mtc1\s+(\$\w+),\s*{re.escape(subtract[1])}')
                original = next((move[1] for row in reversed(window[max(0, j-8):j])
                                 if (move := transfers.fullmatch(row))), None)
                for following in window[j+1:j+6]:
                    saved = _KEEP.fullmatch(following)
                    if saved and saved[2] == subtract[1] and saved[1] == original:
                        return saved[1]
                break
            if re.match(rf'\S+\s+{re.escape(loaded[1])}(?:,|$)', window[j]) or re.fullmatch(
                rf'mtc1\s+\$\w+,\s*{re.escape(loaded[1])}', window[j]
            ):
                break
    return None


def _target_register(assembly, callee, index):
    calls = [i for i, row in enumerate(assembly[:-1]) if re.fullmatch(rf'jal\s+{re.escape(callee)}', row)]
    if len(calls) != 2:
        return None
    slots = [_ARGUMENT.fullmatch(assembly[i+1]) for i in calls]
    if not all(slots) or int(slots[0][1], 0) != int(slots[1][1], 0):
        return None
    offset = int(slots[0][1], 0) + 4*index
    saved = []
    for call in calls:
        window = []
        for row in assembly[call+2:call+26]:
            if _CONTROL.match(row):
                break
            window.append(row)
        saved.append(_written_to_saved(window, offset))
    return saved[0] if saved[0] == saved[1] else None


def _source_calls(part, buffer, before):
    expr = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<call>{IDENT})\s*\(\s*{buffer}\b\s*,')
    for hit in expr.finditer(part.clean, part.opening + 1, before):
        opening = part.clean.find('(', hit.start('call'), hit.end())
        end = close(part.clean, opening)
        suffix = re.match(r'\s*;', part.clean[end:before]) if end else None
        if not suffix:
            continue
        if part.clean[part.opening:hit.start()].rstrip()[-1:] not in (';', '{', '}'):
            continue
        yield hit, end + suffix.end()


def variants(source, name, rows):
    part = view(source, name)
    if not part or not rows or len(rows) > 8192:
        return []
    targets = [row[1].split(';', 1)[0].strip() for row in rows if row[1].strip()]
    proposals = []
    for hit in _REPEATED.finditer(part.clean, part.opening + 1, part.end):
        buf, value = hit['buf'], hit['value']
        index = int(hit['index'], 0)
        arrays = list(re.finditer(rf'(?m)^[ \t]*{FLOAT_TYPE}\s+{buf}\s*\[\s*(\d+)\s*\]\s*;', part.body))
        locals_ = list(re.finditer(rf'(?m)^[ \t]*{FLOAT_TYPE}\s+{value}\s*;',
                                   part.clean[part.opening + 1:hit.start()]))
        if len(arrays) != 1 or len(locals_) != 1 or index >= int(arrays[0][1]):
            continue
        calls = list(_source_calls(part, buf, hit.start()))
        if len(calls) != 2 or calls[0][0]['call'] != calls[1][0]['call']:
            continue
        first, second = calls
        scope = block_path(part, hit.start())
        if not scope or any(block_path(part, call.start()) != scope for call, _ in calls):
            continue
        between = part.clean[first[1]:hit.start()]
        if (_LABEL.search(between) or re.search(rf'\b(?:{value}|goto|break|continue|return)\b', between)
                or re.search(rf'&\s*\(*\s*{value}\b', part.body)):
            continue
        register = _target_register(targets, first[0]['call'], index)
        if not register or value != 'var_' + register.removeprefix('$'):
            continue
        operand = f'{buf}[{hit["index"]}]'
        indent = first[0]['indent']
        before = f'\n{indent}{value} = {hit["seed"]} - {operand};'
        after = f'{value} -= {operand};'
        proposals.append((FAMILY, edit(source, [(first[1], first[1], before),
                                                (hit.start('value'), hit.end(), after)])))
    return proposals[:3]
