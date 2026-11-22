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
SHARED_ZERO = 'shared_setup_reset'
_EXTERN_STORE = re.compile(rf'sw (\$s[0-7]|\$fp), %lo\(({IDENT})\)\((\$\w+)\)')
_SHARED_PHASE = re.compile(
    rf'(?m)^[ \t]*(?P<owner>{IDENT})\s*\.\s*(?P<word>{IDENT})\s*=\s*'
    rf'\((?P<type>u32|unsigned\s+int)\)\s*(?P<param>{IDENT})\s*&\s*~\((?P=type)\)\s*(?P=param)\s*;[ \t]*\n'
    rf'[ \t]*{IDENT}\s*\.\s*{IDENT}\s*=\s*(?P<view>(?P=owner)\s*\.\s*(?P<number>{IDENT}))\s*;[ \t]*\n'
    rf'[ \t]*(?P<external>{IDENT})\s*=\s*(?P<zero>0\.0[fF])\s*;[ \t]*\n'
    rf'[ \t]*\{{[ \t]*\n[ \t]*(?P<float>f32|float)\s+{IDENT}\s*=\s*0\.0[fF]\s*;[ \t]*\n'
    rf'(?P<copy>[ \t]*(?P<carry>{IDENT})\s*=\s*(?P=owner)\s*\.\s*(?P=number)\s*;[ \t]*\n)'
    rf'(?P<call>[ \t]*(?P<setup>{IDENT})\s*\(\s*(?P=param)\s*\)\s*;[ \t]*\n)'
    rf'[ \t]*{IDENT}\s*=\s*0\.0[fF]\s*;[ \t]*\n[ \t]*if\s*\('
)


def _shared_zero_witnesses(rows):
    for i, (kind, target, candidate) in enumerate(rows):
        store = _EXTERN_STORE.fullmatch(target) if kind != ' ' else None
        if not store or candidate != f'sw $zero, %lo({store[2]})({store[3]})' or i + 2 >= len(rows):
            continue
        setup, observed = rows[i + 1][1:]
        copy, rival = rows[i + 2][1:]
        move = re.fullmatch(r'move (\$s[0-7]|\$fp), (\$s[0-7]|\$fp)', copy)
        if (setup == observed and (call := _CALL.fullmatch(setup)) and move and move[2] == store[1]
                and re.fullmatch(r'move (\$s[0-7]|\$fp), \$zero', rival)
                and any(a == f'move {store[1]}, $zero' for _, a, _ in rows[max(0, i - 6):i])):
            yield store[2], call[1]


def shared_zero_variants(source, name, rows, header=''):
    witnesses = set(_shared_zero_witnesses(rows))
    visible = _visible(source, name, header) if witnesses else None
    if not visible:
        return []
    part, context = visible
    macros = set(re.findall(rf'(?m)^\s*#\s*(?:define|undef)\s+({IDENT})', context))
    signature = part.clean[part.clean.rfind('}', 0, part.opening) + 1:part.opening]
    for hit in _SHARED_PHASE.finditer(part.clean, part.opening + 1, part.end):
        owner, carry, external, kind = (hit[key] for key in ('owner', 'carry', 'external', 'float'))
        if ((external, hit['setup']) not in witnesses or macros & set(re.findall(IDENT, hit[0]))
                or _escaped(part.body, owner) or _escaped(part.body, carry) or _escaped(part.body, hit['param'])
                or not re.search(rf'[(,]\s*void\s*\*\s*{hit["param"]}\s*[,)]', signature)
                or re.search(rf'\b{IDENT}\s+\**\s*{hit["param"]}\s*[,;=\[]', part.body)):
            continue
        shape = (rf'(?m)^[ \t]*union\s*\{{\s*{hit["type"]}\s+{hit["word"]}\s*;'
                 rf'\s*{kind}\s+{hit["number"]}\s*;\s*\}}\s*{owner}\s*;')
        declarations = []
        for declaration in (shape, rf'(?m)^[ \t]*{kind}\s+{carry}\s*;'):
            matches = list(re.compile(declaration).finditer(part.clean, part.opening + 1, hit.start()))
            if len(matches) == 1 and part.clean[part.opening:matches[0].start()].rstrip()[-1:] in ('{', '}', ';'):
                declarations.append(matches[0])
        if (len(declarations) != 2 or any(block_path(part, decl.start()) != [part.opening] for decl in declarations)
                or len(re.findall(rf'\}}\s*{owner}\b', part.body)) != 1
                or len(re.findall(rf'\b{kind}\s+{carry}\b', part.body)) != 1
                or len(re.findall(rf'(?m)^[ \t]*extern\s+{kind}\s+{external}\s*;', context)) != 1
                or len(re.findall(rf'\b{kind}\s+{external}\b', context)) != 1
                or re.search(rf'\btypedef\s+(?!float\s+f32\b)[^;{{}}]+?\s+{kind}\s*;', context)):
            continue
        ordered = source[slice(*hit.span('call'))] + source[slice(*hit.span('copy'))]
        trial = edit(source, [(*hit.span('zero'), source[slice(*hit.span('view'))]),
                              (hit.start('copy'), hit.end('call'), ordered)])
        if len(trial.encode()) <= 65536:
            return [(SHARED_ZERO, trial)]
    return []


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
