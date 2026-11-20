"""Diff-gated KMC hypothesis for a flag merged at a shared exit."""

import re

from .integer_repair_support import IDENT, edit, locals_for, refs, view

MERGE_MOVE = re.compile(r'move\s+(\$v[01]),\s*\$a[0-3]')


def variants(source, name, rows):
    changed = [i for i, (mark, _, _) in enumerate(rows) if mark != ' ']
    if len(changed) != 1 or changed[0] == 0:
        return []
    index = changed[0]
    move = MERGE_MOVE.fullmatch(rows[index][1])
    if (not move or rows[index][2] != f'move {move[1]}, $zero'
            or rows[index-1][0] != ' ' or not rows[index-1][1].startswith('bne ')):
        return []

    part = view(source, name)
    if part is None:
        return []
    candidates = []
    for decl in locals_for(part):
        flag = decl['name']
        if decl['type'] not in ('s32', 'u32', 'int') or part.clean[decl.end()-1] != ';':
            continue
        uses = refs(part, decl)
        if len(uses) != 3:
            continue
        zero, merge, test = uses
        label = re.match(rf'\s*=\s*0\s*;\s*goto\s+({IDENT})\s*;', part.clean[zero.end():merge.start()])
        if not label:
            continue
        if not re.fullmatch(rf'\s*=\s*{IDENT}\s*;\s*{label[1]}\s*:\s*if\s*\(\s*',
                            part.clean[merge.end():test.start()]):
            continue
        if not re.match(r'\s*==\s*0\s*\)', part.clean[test.end():]):
            continue
        if re.search(rf'^\s*#\s*define\s+{flag}\b', part.clean, re.M):
            continue
        at = decl.end()-1
        candidates.append(('measured_shared_exit_flag', edit(source, [(at, at, ' = 0')])))
    return candidates if len(candidates) == 1 else []
