"""Reuse a saved smoothing axis for the subsequent clamp field reload."""

import re

from .clamp_return_local import _field
from .compiler_phase_repairs import fresh
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .operand_lifetime_repairs import _escaped, _in_scope, _typed_locals, _visible

FAMILY = 'saved_clamped_field_reload'
_FPR = r'\$f(?:[12]?[0-9]|3[01])'
_SAVED = r'\$f(?:20|22|24|26|28|30)'
_ADDR = rf'({NUMBER})(\(\$\w+\))'
_LOAD = re.compile(rf'lwc1 ({_SAVED}), {_ADDR}')
_ANY_LOAD = re.compile(rf'lwc1 ({_FPR}), {_ADDR}')
_STORE = re.compile(rf'swc1 ({_FPR}), {_ADDR}')
_GLOBAL_VALUE = re.compile(rf'lwc1 ({_FPR}), %lo\(({IDENT})\)\(\$at\)')
_LITERAL = r'\d+\.\d+[fF]'
_FIELD = r'\*[^;={}\n]+?'
_SOURCE = re.compile(
    rf'(?m)^[ \t]*(?P<old>{IDENT})\s*=\s*(?P<field>{_FIELD})\s*;\s*'
    rf'(?P<result>{IDENT})\s*=\s*\(\(\s*(?P<axis>{IDENT}|\({IDENT}\s*\*\s*{_LITERAL}\))'
    rf'\s*-\s*(?P=old)\)\s*\*\s*{_LITERAL}\)\s*\+\s*(?P=old)\s*;\s*'
    rf'(?P=field)\s*=\s*(?P=result)\s*;\s*if\s*\(\s*(?P=result)\s*<\s*\(-(?P<bound>{_LITERAL})\)'
    rf'\s*\)\s*\{{\s*(?P=field)\s*=\s*-(?P=bound)\s*;\s*\}}\s*'
    rf'else\s*if\s*\(\s*(?P=result)\s*>\s*(?P=bound)\s*\)\s*'
    rf'\{{\s*(?P=field)\s*=\s*(?P=bound)\s*;\s*\}}[ \t]*\n'
    rf'(?:[ \t]*{IDENT}\s*=\s*\*\(\(void\s*\*\*\)[^;={{}}\n]+;[ \t]*\n)?'
    rf'(?P<replace>(?P<pad>[ \t]*)(?P<global>{IDENT})\s*-=\s*(?P=field);)'
)


def _evidence(rows):
    targets = [(i, marker, left) for i, (marker, left, _) in enumerate(rows) if left]
    witnesses = set()
    for j in range(2, len(targets)):
        index, mark, line = targets[j]
        load = _LOAD.fullmatch(line)
        store = _STORE.fullmatch(targets[j - 1][2])
        if not (load and mark != ' ' and store and store.groups()[1:] == load.groups()[1:]
                and targets[j - 2][2].startswith('bc1tl ')):
            continue
        end = targets[min(j + 13, len(targets) - 1)][0]
        target = [op for _, _, op in targets[j + 1:j + 14]]
        for follow, line in enumerate(target[:7]):
            value = _GLOBAL_VALUE.fullmatch(line)
            if not follow or not value or target[follow - 1] != f'lui $at, %hi({value[2]})':
                continue
            if not {f'sub.s {value[1]}, {value[1]}, {load[1]}',
                    f'swc1 {value[1]}, %lo({value[2]})($at)'} <= set(target[follow + 1:]):
                continue
            other = [_ANY_LOAD.fullmatch(right) for _, _, right in rows[index:end + 1]]
            if any(alt and alt[1] != load[1] and alt.groups()[1:] == load.groups()[1:] for alt in other):
                witnesses.add((value[2], integer(load[2])))
    return witnesses


def variants(source, name, rows, *, header=''):
    witness = _evidence(rows)
    visible = _visible(source, name, header) if witness else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\btypedef\b[^;\n]*\b(?:volatile|_Atomic)\b[^;\n]*\bf32\s*;', context):
        return []
    locals_f32 = _typed_locals(part, r'(?:f32|float)')
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    snapshot = fresh(source, header, 'repair_saved_axis')
    sites = []
    for m in _SOURCE.finditer(part.clean, part.opening + 1, part.end):
        axis = re.search(IDENT, m['axis'])[0]
        field = _field(m['field'], part.clean[:part.opening])
        if (not field or (m['global'], field[1]) not in witness or axis not in locals_f32
                or axis in (m['old'], m['result']) or _escaped(part.body, axis)
                or not _in_scope(part, locals_f32[axis][1], m.start())):
            continue
        if re.search(rf'\b(?:volatile|_Atomic)\b[^;{{}}\n]*\b(?:{axis}|{m["global"]})\b', context):
            continue
        if re.search(r'/[*/]|#', source[m.start():m.end()]) or macros & set(re.findall(IDENT, m[0])):
            continue
        pad = m['pad']
        original_load = source[slice(*m.span('field'))]
        global_write = m['global']
        c_type = locals_f32[axis][0]
        replacement = (
            f'{pad}{{ {c_type} {snapshot} = {axis};\n{pad}{axis} = {original_load};\n'
            f'{pad}{global_write} -= {axis};\n{pad}{axis} = {snapshot}; }}'
        )
        sites.append((*m.span('replace'), replacement))
        if len(sites) >= 4:
            break
    options = [sites] + [[site] for site in sites] if len(sites) > 1 else [sites]
    return [(FAMILY, edit(source, group)) for group in options if group]
