"""Capture a three-float output before the target's following memory write."""

import re

from .goto_structure_repairs import _paths, parse
from .integer_repair_support import IDENT, edit, view
from .mips_returns import instructions
from .pattern_repairs import close

FAMILY = 'vector_output_capture'
_NUMBER = r'(?:0[xX][0-9a-fA-F]+|0|[1-9]\d*)'
_TYPE = r'(?:f32|float)'
_CALL = re.compile(rf'(?P<name>{IDENT})\s*\(\s*(?P<buf>{IDENT}(?:\.{IDENT})?)\s*,')
_SLOT = re.compile(rf'addiu\s+\$a0,\s*\$sp,\s*({_NUMBER})')
_LOAD = re.compile(rf'lwc1\s+(\$f\w+),\s*({_NUMBER})\(\$sp\)')
_STORE = re.compile(r'(?:swc1|sw|sb|sh)\s+[^,]+,\s*[^()]*\((?!\$sp\))\$\w+\)')
_CONTROL = re.compile(r'(?:b\w*|j\w*|break|syscall)\b')


def _target_site(rows, call):
    slot = _SLOT.fullmatch(rows[call+1])
    if not slot:
        return False
    base = int(slot[1], 0)
    first = [_LOAD.fullmatch(row) for row in rows[call+2:call+5]]
    if (len(first) != 3 or not all(first) or len({row[1] for row in first}) != 3
            or [int(row[2], 0) for row in first] != [base, base+4, base+8]):
        return False
    for row in rows[call+5:call+13]:
        if _CONTROL.match(row):
            break
        if _STORE.fullmatch(row):
            return True
    return False


def _local_array(body, name):
    if '.' not in name:
        return bool(re.search(rf'(?m)^\s*{_TYPE}\s+{name}\s*\[\s*3\s*\]\s*;', body))
    obj, field = name.split('.')
    structs = re.findall(rf'\bstruct\s*{{([^{{}}]+)}}\s*{obj}\s*;', body)
    return len(structs) == 1 and bool(re.search(rf'\b{_TYPE}\s+{field}\s*\[\s*3\s*\]\s*;', structs[0]))


def _buffer_uses_are_reads_or_calls(part, callee, buffer):
    obj = buffer.split('.')[0]
    if re.search(rf'&\s*\(*\s*{obj}\b(?!\s*\.)', part.body):
        return False
    for use in re.finditer(rf'\b{re.escape(buffer)}\b', part.body):
        before = part.body[:use.start()]
        after = part.body[use.end():]
        if re.search(rf'\b{callee}\s*\(\s*$', before) and after.lstrip().startswith(','):
            continue
        element = re.match(r'\s*\[\s*[012]\s*\]', after)
        if re.search(rf'\b{_TYPE}\s+$', before) and re.match(r'\s*\[\s*3\s*\]\s*;', after):
            continue
        if not element or re.match(r'\s*(?:[+*/-]?=(?!=)|\+\+|--)', after[element.end():]):
            return False
        if re.search(r'(?:&|\+\+|--)\s*\(*\s*$', before):
            return False
    return True


def _capture(part, source, stmt, call, following):
    buffer = call['buf']
    component = re.compile(rf'\b{re.escape(buffer)}\s*\[\s*([012])\s*\]')
    mentions = re.compile(rf'\b{re.escape(buffer)}\b')
    simple_assign = re.compile(rf'{IDENT}\s*(?:=|\+=|-=)\s*[^;{{}}]+;')
    found = {}
    saw_store = False
    for next_stmt in following[:10]:
        text = part.clean[next_stmt.start:next_stmt.end]
        if next_stmt.kind != 'simple' or re.search(r'\b\w+\s*\(', text):
            break
        hits = list(mentions.finditer(text))
        if not hits:
            saw_store |= not found and text.startswith('*') and '=' in text
            continue
        match = component.search(text)
        if len(hits) != 1 or not match or not simple_assign.fullmatch(text):
            break
        index = int(match[1])
        if index in found:
            break
        found[index] = (next_stmt.start+match.start(), next_stmt.start+match.end())
        if len(found) == 3:
            break
    if not saw_store or set(found) != {0, 1, 2}:
        return []
    names = [f'repair_vector_{index}' for index in range(3)]
    for index, name in enumerate(names):
        while re.search(rf'\b{name}\b', part.clean):
            name += '_'
        names[index] = name
    declarations = '\n' + ''.join(f'    f32 {name};\n' for name in names)
    offset = call.start()
    indentation = re.match(r'[ \t]*', source[source.rfind('\n', 0, offset)+1:offset])[0]
    captures = ''.join(f'\n{indentation}{name} = {buffer}[{index}];' for index, name in enumerate(names))
    opening = part.opening+1
    return [(opening, opening, declarations), (stmt.end, stmt.end, captures),
            *((*span, names[index]) for index, span in found.items())]


def variants(source, name, asm):
    part = view(source, name) if 'lwc1' in asm and 'jal' in asm else None
    if not part:
        return []
    end = close(part.clean, part.opening, '{', '}')
    if not end:
        return []
    try:
        paths = list(_paths(parse(part.clean, part.opening+1, end-1)))
    except ValueError:
        return []
    calls = {}
    for stmt, trail in paths:
        match = _CALL.match(part.clean, stmt.start, stmt.end) if stmt.kind == 'simple' else None
        if match:
            calls.setdefault(match['name'], []).append((stmt, trail, match))
    rows = instructions(asm)
    choices = []
    for callee, sites in calls.items():
        targets = [i for i, row in enumerate(rows[:-1]) if row == f'jal {callee}']
        if len(targets) != len(sites):
            continue
        for target, (stmt, trail, call) in zip(targets, sites):
            if (not _target_site(rows, target) or not _local_array(part.body, call['buf'])
                    or not _buffer_uses_are_reads_or_calls(part, callee, call['buf'])):
                continue
            siblings, index, _ = trail[-1]
            changes = _capture(part, source, stmt, call, siblings[index+1:])
            if changes:
                choices.append((FAMILY, edit(source, changes)))
    return choices[:3]


ORDER_FAMILY = 'vector_output_load_order'
_WORD = re.compile(rf'lw\s+(\$\w+),\s*({_NUMBER})\(\$(?!sp\b)\w+\)')
_POINTER_READ = re.compile(
    rf'(?P<local>{IDENT})\s*=\s*\*\(\s*\(\s*void\s*(?P<stars>\*\s*\*)\s*\)'
    rf'\s*\(\s*\(\s*\(\s*char\s*\*\s*\)\s*{IDENT}\s*\)\s*\+\s*(?P<offset>{_NUMBER})\s*\)\s*\)\s*;'
)


def _ordered_site(target, candidate, old_call, new_call):
    if new_call+5 >= len(target) or not _target_site(target, new_call):
        return None
    pointer_row = target[new_call+5]
    pointer = _WORD.fullmatch(pointer_row)
    expected = [target[new_call+1], pointer_row, *target[new_call+2:new_call+5]]
    if not pointer or candidate[old_call+1:old_call+6] != expected:
        return None
    later = candidate[old_call+6:old_call+10]
    for op in target[new_call+6:new_call+10]:
        if _CONTROL.match(op):
            break
        if op in later and _STORE.fullmatch(op) and op.endswith(f'({pointer[1]})'):
            return int(pointer[2], 0)
    return None


def _call_indexes(code):
    calls = {}
    for index, op in enumerate(code):
        if op.startswith('jal '):
            calls.setdefault(op[4:], []).append(index)
    return calls


def _ordered_load_edits(part, buffer, following, offset):
    component = re.compile(
        rf'(?P<local>{IDENT})\s*=\s*(?P<read>{re.escape(buffer)}\s*\[\s*(?P<index>[012])\s*\])\s*;'
    )
    if len(following) < 4 or any(stmt.kind != 'simple' for stmt in following[:4]):
        return []
    reads = [component.fullmatch(part.clean, stmt.start, stmt.end) for stmt in following[:3]]
    pointer = _POINTER_READ.fullmatch(part.clean, following[3].start, following[3].end)
    if (not all(reads) or [hit['index'] for hit in reads] != ['0', '1', '2']
            or not pointer or len({pointer['local'], *(hit['local'] for hit in reads)}) != 4
            or int(pointer['offset'], 0) != offset):
        return []
    star_start, star_end = pointer.span('stars')
    changes = [(star_start, star_end, '* volatile *')]
    for hit in reads:
        start, end = hit.span('read')
        changes.append((start, end, f'((volatile float *) {buffer})[{hit["index"]}]'))
    return changes


def ordered_snapshot_variants(source, name, rows):
    """Trial the same four loads with their observed ordering on KMC."""
    target = [op for _, op, _ in rows if op]
    candidate = [op for _, _, op in rows if op]
    old_calls = _call_indexes(candidate)
    targets = {}
    for callee, indexes in _call_indexes(target).items():
        previous = old_calls.get(callee, ())
        if len(previous) != len(indexes):
            continue
        offsets = [_ordered_site(target, candidate, old, new) for old, new in zip(previous, indexes)]
        if any(offset is not None for offset in offsets):
            targets[callee] = offsets
    if not targets:
        return []
    part = view(source, name)
    if not part:
        return []
    end = close(part.clean, part.opening, '{', '}')
    if not end:
        return []
    try:
        paths = _paths(parse(part.clean, part.opening+1, end-1))
        sites = {}
        for stmt, trail in paths:
            call = _CALL.match(part.clean, stmt.start, stmt.end) if stmt.kind == 'simple' else None
            if call and call['name'] in targets:
                sites.setdefault(call['name'], []).append((trail, call['buf']))
    except ValueError:
        return []
    result = []
    for callee, calls in sites.items():
        if len(calls) != len(targets[callee]):
            continue
        for (trail, buffer), offset in zip(calls, targets[callee]):
            if (offset is None or not _local_array(part.body, buffer)
                    or not _buffer_uses_are_reads_or_calls(part, callee, buffer)):
                continue
            siblings, index, _ = trail[-1]
            changes = _ordered_load_edits(part, buffer, siblings[index+1:], offset)
            if changes:
                result.append((ORDER_FAMILY, edit(source, changes)))
    return result[:2]
