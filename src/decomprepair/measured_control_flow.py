"""Diff-gated KMC hypothesis for a flag merged at a shared exit."""

import re

from .integer_repair_support import IDENT, edit, locals_for, refs, view

MERGE_MOVE = re.compile(r'move\s+(\$v[01]),\s*\$a[0-3]')


def _counted_list_result(source, name, rows, index):
    """Return the zero-initialized count directly on both list paths."""
    if index + 1 >= len(rows) or tuple(rows[index][1:]) != ('move $v0, $a1', 'move $v0, $zero'):
        return []
    branch = 'beqz $v1, '
    if rows[index - 1][1] != rows[index - 1][2] or not rows[index - 1][1].startswith(branch):
        return []
    if not rows[index + 1][1].startswith('lhu $v0, ') or rows[index + 1][1] != rows[index + 1][2]:
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__|goto)\b', part.body):
        return []
    pattern = re.compile(
        rf'(?m)^(?P<initial>[ \t]*(?P<result>{IDENT}) = 0;\n)'
        rf'[ \t]*if \((?P<cursor>{IDENT}) != NULL\) \{{\s*do \{{'
        rf'(?P<loop>[^{{}}]+)\}} while \((?P=cursor) != NULL\);\n'
        rf'(?P<copy>[ \t]*(?P=result) = (?P<count>{IDENT});\n)'
        rf'[ \t]*\}}\s*return (?P<return>(?P=result));\s*\}}\s*$'
    )
    hit = pattern.search(part.clean, part.opening + 1, part.end)
    if not hit:
        return []
    count, result = hit['count'], hit['result']
    declaration = re.search(rf'(?m)^[ \t]*s32 {result};\n', part.body)
    if not declaration or len(re.findall(rf'\b{result}\b', part.body)) != 4:
        return []
    earlier = part.clean[part.opening + 1:hit.start()]
    if (len(re.findall(rf'\b{count}\b', earlier)) != 2
            or not re.search(rf'\bs32 {count};', earlier) or not re.search(rf'\b{count} = 0;', earlier)
            or len(re.findall(rf'\b{count}\b', hit['loop'])) != 1
            or not re.search(rf'\b{count} \+= {IDENT} == {IDENT};', hit['loop'])):
        return []
    start, end = (part.opening + 1 + pos for pos in declaration.span())
    return [('measured_counted_list_result', edit(source, [
        (start, end, ''), (*hit.span('initial'), ''), (*hit.span('copy'), ''), (*hit.span('return'), count),
    ]))]


def variants(source, name, rows):
    changed = [i for i, (mark, _, _) in enumerate(rows) if mark != ' ']
    if len(changed) != 1 or changed[0] == 0:
        return []
    index = changed[0]
    if candidate := _counted_list_result(source, name, rows, index):
        return candidate
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
