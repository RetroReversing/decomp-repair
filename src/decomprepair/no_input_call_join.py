"""Balance a proven no-input call with a witnessed scan flag copy."""

import re

from .callee_contracts import signature
from .csource import _blank, find
from .integer_repair_support import IDENT, edit
from .local_flow import Flow
from .operand_lifetime_repairs import _in_scope, _typed_locals, _visible

FAMILY = 'verified_no_input_call_scan_join'
_ASSIGN_FLAG = re.compile(r'addiu (\$s[0-7]), \$zero, 1')
_CALL = re.compile(rf'jal ({IDENT})')
_ARGUMENT = re.compile(r'move \$a0, \$s[0-7]')
_JOIN = re.compile(
    rf'(?m)^(?P<label>[ \t]*{IDENT}):[ \t]*\n(?P<pad>[ \t]*)'
    rf'if\s*\(\s*(?P<test>{IDENT})\s*!=\s*0\s*\)'
)
_NULL_CASE = re.compile(
    rf'(?m)^[ \t]*if\s*\(\s*(?P<ptr>{IDENT})\s*==\s*NULL\s*\)\s*\{{\s*'
    rf'(?P<flag>{IDENT})\s*=\s*1\s*;\s*(?P<iter>{IDENT})\s*=\s*(?P<invoke>(?P<callee>{IDENT})\(\s*'
    rf'(?P<arg>{IDENT})\s*\))\s*;\s*goto\s+(?P<label>{IDENT})\s*;\s*\}}'
)
_FPTR_DECL = re.compile(rf'(?m)^[ \t]*void\s*\*\s*(?P<name>{IDENT})\s*;')
_RETURN = r'(?P<result>s32|u32|void\s*\*)'


def witnesses(rows):
    """Find one excess argument move and the matching later scan flag lifetime."""
    wanted = set()
    for index in range(2, len(rows) - 2):
        call = _CALL.fullmatch(rows[index][1])
        flag = _ASSIGN_FLAG.fullmatch(rows[index + 1][1])
        before = rows[index - 1]
        if (not call or not flag or rows[index][1] != rows[index][2] or before[1] or before[2] != flag[0]
                or not _ARGUMENT.fullmatch(rows[index + 1][2]) or rows[index - 2][1] != rows[index + 1][2]):
            continue
        for first, second in zip(rows[index + 2:index + 130], rows[index + 3:index + 131]):
            if first[1] != f'move $v0, {flag[1]}' or first[2]:
                continue
            if second[1].startswith('beqz $v0, ') and second[2] == second[1].replace('$v0', flag[1], 1):
                wanted.add(call[1])
                break
    return wanted if 0 < len(wanted) <= 2 else set()


def _confirmed_result(source, callee):
    clean = _blank(source)
    if re.search(rf'(?m)^\s*#\s*(?:define|undef)\s+{callee}\b', clean):
        return None
    span = find(clean, callee)
    if not span:
        return None
    definition = re.fullmatch(
        rf'\s*{_RETURN}\s*{callee}\s*\(\s*void\s*\)\s*\{{\s*return\s+{IDENT}\s*;\s*\}}\s*',
        clean[span[0]:span[1]],
    )
    return definition['result'] if definition else None


def _pointer_locals(part):
    for decl in _FPTR_DECL.finditer(part.clean, part.opening + 1, part.end):
        name = decl['name']
        # An ordinary local declaration cannot be an assignment or a shadow.
        before = part.clean[part.opening + 1:decl.start()].rstrip()
        bindings = re.findall(rf'\b(?:void|s[0-9]+|u[0-9]+|f[0-9]+|char|int|long|short|float|double)\s*'
                              rf'\**\s*{name}\s*(?=[;,=\[])', part.body)
        if (not before or before[-1] in ';{}') and len(bindings) == 1:
            yield decl


def variants(source, name, rows, header, matched_callees):
    qualified = witnesses(rows) & matched_callees.keys()
    visible = _visible(source, name, header) if qualified else None
    if not visible:
        return []
    part, context = visible
    ordinary = _typed_locals(part, r'(?:s32|int|u32|s8|u8|s16|u16)')
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    pointers = {decl['name']: decl for decl in _pointer_locals(part)}
    try:
        flow = Flow(part, pointers.values())
    except (ValueError, RecursionError):
        return []
    proposals = []
    for arm in _NULL_CASE.finditer(part.clean, part.opening + 1, part.end):
        callee, ptr, flag, arg, iterator = (arm[key] for key in ('callee', 'ptr', 'flag', 'arg', 'iter'))
        if (callee not in qualified or ptr == iterator or ptr not in flow.names or iterator not in pointers
                or flag not in ordinary or arg not in ordinary or flag == arg or re.search(rf'\b{callee}\b', header)
                or macros & (set(re.findall(IDENT, arm[0])) - {'NULL'})):
            continue
        actual = _confirmed_result(matched_callees[callee], callee)
        decls = list(re.finditer(rf'(?m)^[ \t]*{_RETURN}\s*{callee}\s*\(\s*([^()]*)\s*\)\s*;',
                                part.clean[:part.opening]))
        if not actual or len(decls) != 1 or len(re.findall(rf'\b{callee}\b', part.clean)) != 2:
            continue
        declaration = decls[0]
        declared = signature(declaration['result'], declaration[2], named=False)
        if declared not in {('void*', (t,)) for t in ('s8', 's16', 's32', 'u8', 'u16', 'u32')}:
            continue
        joins = [m for m in _JOIN.finditer(part.clean, arm.end(), part.end)
                 if (m['label'].strip(), m['test']) == (arm['label'], flag)]
        if len(joins) != 1:
            continue
        join = joins[0]
        writes = re.findall(rf'\b{flag}\s*=\s*[01]\s*;', part.body)
        if len(re.findall(rf'\b{flag}\b', part.body)) != len(writes) + 2:
            continue
        if (not flow.dead(ptr, join.start('test')) or not _in_scope(part, pointers[ptr].start(), join.start())
                or not _in_scope(part, pointers[iterator].start(), arm.start())
                or any(not _in_scope(part, ordinary[local][1], arm.start()) for local in (flag, arg))
                or not _in_scope(part, ordinary[flag][1], join.start())
                or macros & {ordinary[flag][0], ordinary[arg][0], actual}):
            continue
        # Keep the mode value in the pointer-sized local only across its zero test.
        # The CFG proves the old pointer is dead before any use on either edge.
        pad = join['pad']
        replacement = f'{join["label"]}:\n{pad}{ptr} = (void *) {flag};\n{pad}if ({ptr} != 0)'
        cast = '(void *) ' if signature(actual, 'void', named=True)[0] != 'void*' else ''
        changes = [
            (declaration.start('result'), declaration.end(), f'{actual} {callee}(void);'),
            (*arm.span('invoke'), f'{cast}{callee}()'),
            (*join.span(), replacement),
        ]
        proposals.append((FAMILY, edit(source, changes)))
    return proposals[:2]
