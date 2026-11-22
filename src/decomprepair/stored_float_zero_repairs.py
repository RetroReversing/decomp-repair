"""Recover a saved zero word reinterpreted as a float for a late update."""

import re

from .goto_structure_repairs import _children, _indent_of, _paths, parse
from .integer_repair_support import edit, view
from .mips_returns import instructions
from .pattern_repairs import close

FAMILY = 'stored_float_zero'
_NUMBER = r'(?:0[xX][0-9a-fA-F]+|0|[1-9]\d*)'
_FPR = r'\$f[astv]?\d+'
_F32 = r'(?:f32|float)'
_MTC = re.compile(rf'mtc1\s+(\$s[0-7]),\s*({_FPR})')
_ADD = re.compile(rf'add\.s\s+({_FPR}),\s*({_FPR}),\s*({_FPR})')
_STORE = re.compile(rf'swc1\s+({_FPR}),\s*({_NUMBER})\((\$s[0-7])\)')
_INCOMING = re.compile(r'(?:addu\s+(\$s[0-7]),\s*\$a0,\s*\$zero|move\s+(\$s[0-7]),\s*\$a0)')
_ZERO = re.compile(r'(?:addu\s+\$s[0-7],\s*\$zero,\s*\$zero|move\s+\$s[0-7],\s*\$zero)')
_REGISTER_USE = re.compile(r'(\w+)\s+(\$s[0-7])(?:,|$)')
_READS = {'sw', 'sb', 'sh', 'sd', 'swl', 'swr', 'mtc1', 'dmtc1', 'ctc1'}
_BRANCH = re.compile(r'(?:b\w*|j\w*)\b')
_FIELD = re.compile(rf'\*{_F32}\*char\*arg0\+({_NUMBER})')
_STACK_ZERO = re.compile(r'sp[0-9a-fA-F]+=0\.0[fF];')
_ZERO_FLOAT = re.compile(r'\b0\.0[fF]\b')


def _target_fields(asm):
    rows = instructions(asm)
    incoming = {hit[1] or hit[2] for row in rows[:24] if (hit := _INCOMING.fullmatch(row))}
    if len(incoming) != 1:
        return set()
    base = incoming.pop()
    writes = {}
    offsets = set()
    for index, row in enumerate(rows):
        use = _REGISTER_USE.match(row)
        if use and use[1] not in _READS and not _BRANCH.match(row):
            writes.setdefault(use[2], []).append(row)
        transfer = _MTC.fullmatch(row)
        if not transfer:
            continue
        known = writes.get(transfer[1], [])
        if len(known) != 2 or not all(_ZERO.fullmatch(move) for move in known):
            continue
        for i in range(index+1, min(index+7, len(rows))):
            addition = _ADD.fullmatch(rows[i])
            if not addition or transfer[2] not in (addition[2], addition[3]):
                continue
            for following in rows[i+1:i+7]:
                store = _STORE.fullmatch(following)
                if store and store[1] == addition[1] and store[3] == base:
                    offsets.add(int(store[2], 0))
                    break
    return offsets


def _compact(text):
    return re.sub(r'[()\s]', '', text)


def _field_sites(part, paths, offset):
    reset, update = [], []
    for statement, trail in paths:
        if statement.kind != 'simple':
            continue
        line = part.clean[statement.start:statement.end]
        left, equals, right = line.partition('=')
        field = _FIELD.fullmatch(_compact(left))
        if not equals or not field or int(field[1], 0) != offset:
            continue
        literals = list(_ZERO_FLOAT.finditer(right))
        if len(literals) != 1:
            continue
        position = statement.start + len(left) + 1
        site = (statement, trail, (position + literals[0].start(), position + literals[0].end()))
        if _compact(right).lower() == '0.0f;':
            reset.append(site)
        elif re.fullmatch(rf'{_F32}?{re.escape(_compact(left))}\+0\.0[fF];', _compact(right)):
            update.append(site)
    return (reset[0], update[0]) if len(reset) == len(update) == 1 else None


def variants(source, name, asm):
    if not asm or not re.search(r'\bmtc1\s+\$s[0-7]\b', asm):
        return []
    part = view(source, name)
    if not part or re.search(r'\barg0\s*=(?!=)|\bgoto\s*\*|&&\s*\w+\s*;', part.body):
        return []
    if not re.search(rf'\b{re.escape(name)}\s*\(\s*[^,;{{}}()]*\barg0\s*(?:,|\))', part.clean[:part.opening]):
        return []
    offsets = _target_fields(asm)
    if not offsets:
        return []
    body_end = close(part.clean, part.opening, '{', '}')
    if not body_end:
        return []
    try:
        paths = list(_paths(parse(part.clean, part.opening+1, body_end-1)))
    except ValueError:
        return []
    for offset in sorted(offsets):
        sites = _field_sites(part, paths, offset)
        if not sites:
            continue
        (reset, reset_path, reset_zero), (update, update_path, update_zero) = sites
        owner = reset_path[-2][2] if len(reset_path) >= 2 else None
        if owner is None or not any(block['block'] and block['stmts'] is reset_path[-1][0] for block in _children(owner)):
            continue
        parent, update_index, _ = update_path[-1]
        switch_index = next((idx for block, idx, owner in reset_path
                             if block is parent and owner is not None and owner.kind == 'switch'), None)
        if switch_index is None or switch_index >= update_index:
            continue
        anchor = next((stmt for stmt in reversed(parent[max(0, switch_index-20):switch_index])
                       if stmt.kind == 'simple' and _STACK_ZERO.fullmatch(
                           _compact(part.clean[stmt.start:stmt.end]))), None)
        if not anchor or any(stmt.kind == 'case' and anchor.start < stmt.start < update.start for stmt in parent):
            continue
        labels = {stmt.parts['name'] for stmt, _ in paths if stmt.kind == 'label'
                  and anchor.start < stmt.start <= update.start}
        if any(stmt.kind == 'goto' and stmt.parts['target'] in labels
               and not anchor.start < stmt.start < update.start for stmt, _ in paths):
            continue
        carrier = 'repair_saved_zero'
        while re.search(rf'\b{carrier}\b', part.clean):
            carrier += '_'
        edits = [
            (part.opening+1, part.opening+1, f'\n    union {{ unsigned int bits; float number; }} {carrier};'),
            (anchor.start, anchor.start, f'{carrier}.bits = 0;\n{_indent_of(source, anchor.start)}'),
            (reset.start, reset.start, f'{carrier}.bits = 0;\n{_indent_of(source, reset.start)}'),
            (*reset_zero, f'{carrier}.number'),
            (*update_zero, f'{carrier}.number'),
        ]
        return [(FAMILY, edit(source, edits))]
    return []
