"""Give a phase-local float initializer its own scope before a setup call."""

import re

from .call_lifetime_repairs import block_path
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .operand_lifetime_repairs import _escaped, _visible
from .pattern_repairs import close

FAMILY = 'scoped_float_phase_initializer'
_FLAG = re.compile(rf'lbu \$v0, %lo\(({IDENT})\)\(\$v0\)')
_CALL = re.compile(rf'jal ({IDENT})')
_BYTE = re.compile(rf'lbu \$v0, ({NUMBER})\((\$\w+)\)')
_LABEL = re.compile(rf'(?m)^(?P<pad>[ \t]*)(?!default\b)(?P<name>{IDENT})\s*:(?!:)')
_GOTO = re.compile(rf'\bgoto\s+({IDENT})\s*;')
_HEAD = re.compile(
    rf'(?m)^[ \t]*{IDENT}\s*\.\s*{IDENT}\s*=\s*0\.0[fF]\s*;[ \t]*\n'
    rf'[ \t]*{IDENT}\s*=\s*0\.0[fF]\s*;[ \t]*\n'
    rf'(?P<copy_line>(?P<pad>[ \t]*){IDENT}\s*=\s*{IDENT}\s*\.\s*{IDENT}\s*;[ \t]*\n)'
    rf'[ \t]*(?P<setup>{IDENT})\([^;{{}}\n]+\)\s*;[ \t]*\n'
    rf'[ \t]*{IDENT}\s*=\s*0\.0[fF]\s*;[ \t]*\n'
    rf'[ \t]*if\s*\(\s*(?P<guard>{IDENT})\s*!=\s*0\s*\)\s*{{'
)
_AFTER_GUARD = re.compile(
    rf'(?P<init>[ \t]*\n[ \t]*(?P<local>{IDENT})\s*=\s*(?P<value>0\.0[fF])\s*;[ \t]*\n)'
    rf'[ \t]*{IDENT}\s*=\s*\*\(\(u8\s*\*\)\s*\(\(\(char\s*\*\)\s*{IDENT}\)'
    rf'\s*\+\s*(?P<offset>{NUMBER})\)\s*\)\s*;'
)


def _witnesses(rows):
    linked = [(a, b, i) for i, (_, a, b) in enumerate(rows) if a]
    for index, (target, candidate, _) in enumerate(linked[:-3]):
        load = _BYTE.fullmatch(target)
        if not load or target != candidate:
            continue
        expected, actual, branch_index = linked[index + 1]
        if (expected == actual or not expected.startswith('beqz $v0, ')
                or expected.partition(' [bytes ')[0] != actual.partition(' [bytes ')[0]
                or linked[index + 2][:2] != ('addiu $v0, $v0, -1',) * 2
                or linked[index + 3][:2] != (f'sb $v0, {load[1]}({load[2]})',) * 2):
            continue
        extra = [line for _, _, line in rows[branch_index + 1:linked[index + 2][2]] if line]
        if len(extra) != 1 or not re.fullmatch(r'move \$s[0-7], \$zero', extra[0]):
            continue
        for i in range(max(5, index - 22), index - 6):
            a, b, _ = linked[i]
            flag = _FLAG.fullmatch(a)
            if not flag or a != b:
                continue
            call = [m[1] for op, actual_op, _ in linked[i - 5:i] if op == actual_op and (m := _CALL.fullmatch(op))]
            conditional = [op for op, _, _ in linked[i + 1:i + 4] if op.startswith('beqz $v0, ')]
            if len(call) == len(conditional) == 1:
                yield call[0], flag[1], integer(load[1])


def _scope_end(part, start, after):
    path = block_path(part, start)
    external = set(_GOTO.findall(part.clean, part.opening + 1, start))
    for end in _LABEL.finditer(part.clean, after, part.end):
        stop = end.start()
        if end['name'] not in external or block_path(part, stop) != path:
            continue
        body = part.clean[start:stop]
        labels = {hit['name'] for hit in _LABEL.finditer(body)}
        if (external & labels or labels.intersection(_GOTO.findall(part.clean, stop, part.end))
                or not re.search(rf'\bgoto\s+{IDENT}\s*;\s*$', body)):
            return None
        switches = {start + hit.end() - 1 for hit in re.finditer(r'\bswitch\s*\([^;{}]+\)\s*{', body)}
        cases = re.finditer(r'\b(?:default|case\s+[^:;{}]+)\s*:', body)
        if any(not switches.intersection(block_path(part, start + case.start())) for case in cases):
            return None
        return end
    return None


def variants(source, name, rows, *, header='', max_bytes=65536):
    witnesses = set(_witnesses(rows))
    visible = _visible(source, name, header) if witnesses else None
    if not visible:
        return []
    part, context = visible
    macros = set(re.findall(rf'(?m)^\s*#\s*(?:define|undef)\s+({IDENT})', context))
    if (macros & {'f32', 'u8'} or re.search(r'(?m)^\s*#\s*pragma\s+STDC\s+FENV_ACCESS\s+ON', context)
            or any(' '.join(typ.split()) != 'float'
                   for typ in re.findall(r'\btypedef\s+([^;{}]+?)\s+f32\s*;', context))):
        return []
    trials = []
    for head in _HEAD.finditer(part.clean, part.opening + 1, part.end):
        guard_end = close(part.clean, head.end() - 1, '{', '}')
        phase = _AFTER_GUARD.match(part.clean, guard_end) if guard_end else None
        if not phase or (head['setup'], head['guard'], integer(phase['offset'])) not in witnesses:
            continue
        name = phase['local']
        insert = head.start('copy_line')
        stop = _scope_end(part, insert, phase.end())
        if (not stop or _escaped(part.body, name)
                or macros & set(re.findall(IDENT, part.clean[head.start():phase.end()]))):
            continue
        words = re.compile(rf'\b{name}\b')
        declarations = list(re.finditer(rf'(?m)^[ \t]*(?P<type>f32|float)\s+{name}\s*;[ \t]*\n',
                                        part.clean[part.opening + 1:insert]))
        if (len(declarations) != 1 or len(words.findall(part.clean, part.opening + 1, insert)) != 1
                or words.search(part.clean, stop.start(), part.end) or words.search(part.clean, insert, phase.start())):
            continue
        declaration = declarations[0]
        if not words.search(part.clean, phase.end(), stop.start()):
            continue
        pad = head['pad']
        original = tuple(part.opening + 1 + n for n in declaration.span())
        init_start = phase.start('init') + len(phase['init'].split('\n', 1)[0]) + 1
        trial = edit(source, [(*original, ''), (init_start, phase.end('init'), ''),
                              (insert, insert, f'{pad}{{\n{pad}{declaration["type"]} {name} = {phase["value"]};\n'),
                              (stop.start(), stop.start(), f'{stop["pad"]}}}\n')])
        if len(trial.encode()) <= max_bytes:
            trials.append((FAMILY, trial))
    return trials if len(trials) == 1 else []
