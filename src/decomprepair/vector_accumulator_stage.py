"""Consume a stack vector's component in its saved accumulator after the call."""

import re

from .goto_structure_repairs import _paths, parse
from .integer_repair_support import IDENT, edit, view
from .mips_returns import instructions
from .pattern_repairs import close
from .stack_call_output_repairs import _ARGUMENT, _CONTROL, _KEEP, _READ
from .vector_output_capture import _buffer_uses_are_reads_or_calls, _local_array

FAMILY = 'vector_accumulator_stage'
FAMILIES = (FAMILY,)
_FLOAT = r'(?:f32|float)'
_SAVED = r'\$(?:fp|s[0-7])'
_FINAL = re.compile(
    rf'(?P<dest>var_(?:fp|s[0-7]))\s*=\s*\(\(\s*(?P<old>temp_(?:fp|s[0-7])(?:_\d+)?)\s*'
    rf'\+\s*(?P<value>{IDENT})\s*\)\s*\+\s*(?P<buf>{IDENT}(?:\.{IDENT})?)'
    r'\s*\[\s*(?P<index>[012])\s*\]\s*\)\s*\+\s*(?P<remaining>[^;]+);')
_ADD = re.compile(r'add\.s\s+(\$f\w+),\s*\1,\s*(\$f\w+)')
_TRANSFER = re.compile(rf'mtc1\s+({_SAVED}),\s*(\$f\w+)')


def _target_add(rows, callee, occurrence, count, component, saved):
    calls = [index for index, row in enumerate(rows[:-1]) if row == f'jal {callee}']
    if len(calls) != count:
        return False
    call = calls[occurrence]
    slot = _ARGUMENT.fullmatch(rows[call+1])
    if not slot:
        return False
    offset = int(slot[1], 0) + 4*component
    loaded = set()
    carriers = set()
    summed = set()
    for row in rows[call+2:call+24]:
        if _CONTROL.match(row):
            break
        if (store := _KEEP.fullmatch(row)) and store[1] == saved and store[2] in summed:
            return True
        load = _READ.fullmatch(row)
        transfer = _TRANSFER.fullmatch(row)
        add = _ADD.fullmatch(row)
        matches_sum = add and add[1] in carriers and add[2] in loaded
        written = re.match(r'(?:lw[cd]1|l[wd]c1|\w+\.[sdw])\s+(\$f\w+),', row)
        target = transfer[2] if transfer else written[1] if written else None
        if target:
            loaded.discard(target)
            carriers.discard(target)
            summed.discard(target)
        if load and int(load[2], 0) == offset:
            loaded.add(load[1])
        if transfer and transfer[1] == saved:
            carriers.add(transfer[2])
        if matches_sum:
            summed.add(add[1])
    return False


def _zero_carrier(part, destination, before, trail, paths):
    """An already initialized zero representation used to seed the destination."""
    prior = part.clean[part.opening:before]
    init = re.search(rf'\b{destination}\s*=\s*({IDENT})\.({IDENT})\s*;', prior)
    if not init:
        return None
    obj, member = init.groups()
    binding = re.search(rf'\bunion\s*{{(?P<body>[^{{}}]+)}}\s*{obj}\s*;', part.body)
    if not binding or re.search(rf'&\s*\(*\s*{obj}\b', part.body):
        return None
    word = re.search(rf'\bu32\s+({IDENT})\s*;', binding['body'])
    if not word or not re.search(rf'\b{_FLOAT}\s+{member}\s*;', binding['body']):
        return None
    identifier = rf'\b{obj}\s*\.\s*{word[1]}\b'
    matches = list(re.finditer(identifier, part.body))
    zero = rf'\s*=\s*(?:0|\(u32\)\s*({IDENT})\s*&\s*~\(u32\)\s*\1)\s*;'
    if not matches or not all(re.match(zero, part.body[match.end():]) for match in matches):
        return None
    origin = next((hit for hit in re.finditer(identifier + zero, prior[:init.start()])), None)
    if not origin:
        return None
    word_at = part.opening + origin.start()
    init_at = part.opening + init.start()
    for siblings, index, _ in trail:
        starts = {stmt.start for stmt in siblings[:index]}
        if word_at not in starts or init_at not in starts:
            continue
        here = siblings[index]
        if any(word_at < stmt.start < here.start and stmt.kind in {'label', 'case'}
               for stmt in siblings[:index]):
            continue
        labels = {stmt.parts['name'] for stmt, _ in paths
                  if here.start <= stmt.start < here.end and stmt.kind == 'label'}
        if any(stmt.kind == 'goto' and stmt.start < word_at and stmt.parts['target'] in labels
               for stmt, _ in paths):
            continue
        break
    else:
        return None
    if re.search(rf'\b{obj}\s*\.\s*{member}\s*(?:=(?!=)|[+*/-]=|\+\+|--)', part.body):
        return None
    return f'{obj}.{member}'


def _capture(source, statement, final, old, call, seed):
    indent = source[source.rfind('\n', 0, call.start)+1:call.start]
    if indent.strip():
        return None
    dest, value, buf, index = (final[k] for k in ('dest', 'value', 'buf', 'index'))
    additions = f'\n{indent}{dest} += {value};\n{indent}{dest} += {buf}[{index}];'
    return edit(source, [(old.start, old.end, f'{dest} = {seed} - {value};'),
                         (call.end, call.end, additions),
                         (statement.start, statement.end, f'{dest} += {final["remaining"]};')])


def variants(source, name, asm):
    part = view(source, name) if asm and 'add.s' in asm and 'lwc1' in asm else None
    if not part:
        return []
    end = close(part.clean, part.opening, '{', '}')
    if not end:
        return []
    try:
        paths = list(_paths(parse(part.clean, part.opening+1, end-1)))
    except ValueError:
        return []
    rows = instructions(asm)
    choices = []
    for statement, trail in paths:
        if statement.kind != 'simple':
            continue
        final = _FINAL.fullmatch(part.clean[statement.start:statement.end])
        if not final:
            continue
        siblings, index, _ = trail[-1]
        dest, temp, value, buf, component, remaining = (
            final[key] for key in ('dest', 'old', 'value', 'buf', 'index', 'remaining'))
        if not _local_array(part.body, buf) or re.search(rf'\b(?:{dest}|{temp})\b', remaining):
            continue
        if not re.search(rf'\bextern\s+{_FLOAT}\s+{value}\s*;', part.clean[:part.opening]):
            continue
        if any(not re.search(rf'(?m)^\s*{_FLOAT}\s+{variable}\s*;', part.body)
               or re.search(rf'&\s*\(*\s*{variable}\b', part.body) for variable in (dest, temp)):
            continue
        seed = re.compile(rf'{temp}\s*=\s*0\.0[fF]\s*-\s*{value}\s*;')
        old = next((stmt for stmt in reversed(siblings[:index])
                    if stmt.kind == 'simple' and seed.fullmatch(part.clean[stmt.start:stmt.end])), None)
        if not old or len(re.findall(rf'\b{temp}\b', part.body)) != 3:
            continue
        between = part.clean[old.end:statement.start]
        if re.search(rf'\b{dest}\b|\b(?:goto|return|continue|break)\b', between):
            continue
        start_tags = [stmt.kind for stmt in siblings if old.start < stmt.start < statement.start]
        if 'label' in start_tags or 'case' in start_tags:
            continue
        call_pattern = re.compile(rf'(?P<callee>{IDENT})\s*\(\s*{re.escape(buf)}\s*,')
        calls = [(stmt, match['callee']) for stmt, _ in paths
                 if stmt.kind == 'simple' and (match := call_pattern.match(part.clean, stmt.start, stmt.end))]
        eligible = [(stmt, callee) for stmt, callee in calls
                    if old.end <= stmt.start < statement.start and stmt in siblings[:index]]
        if len(eligible) != 1:
            continue
        call, callee = eligible[0]
        sites = [stmt for stmt, label in calls if label == callee]
        if not _buffer_uses_are_reads_or_calls(part, callee, buf):
            continue
        if not _target_add(rows, callee, sites.index(call), len(sites), int(component), '$'+dest[4:]):
            continue
        values = [_zero_carrier(part, dest, old.start, trail, paths), '0.0f']
        choices.extend((FAMILY, child) for value in values if value
                       and (child := _capture(source, statement, final, old, call, value)))
    return choices[:4]
