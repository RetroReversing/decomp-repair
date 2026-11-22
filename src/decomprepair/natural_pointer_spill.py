"""Recover a natural pointer spill when a shared zero changes its register competition."""

import re
from collections import Counter

from .call_lifetime_repairs import block_path
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .operand_lifetime_repairs import _escaped, _visible
from .pattern_repairs import close

FAMILY = 'natural_pointer_spill'
REG = r'\$[a-z0-9]+'
_LOAD = re.compile(rf'lw ({REG}), ({NUMBER})\(({REG})\)')
_STORE = re.compile(rf'sw ({REG}), ({NUMBER})\(\$sp\)')
_CALL = re.compile(rf'jal ({IDENT})')
_STRUCT = re.compile(r'\bstruct\s*\{')
_TAIL = re.compile(
    rf'(?m)^[ \t]*(?:u32|unsigned\s+int)\s+(?P<pad>{IDENT})\s*;[ \t]*\n'
    rf'[ \t]*void\s*\*\s*(?P<member>{IDENT})\s*;[ \t]*\n(?=\s*$)'
)
_POINTER_READ = re.compile(
    rf'(?m)^[ \t]*(?P<local>{IDENT})\s*=\s*\*\(\(void\s*\*\*\)\s*\(\(\(char\s*\*\)'
    rf'\s*(?P<param>{IDENT})\)\s*\+\s*(?P<offset>{NUMBER})\)\s*\)\s*;[ \t]*\n'
)
_WORD_FLOAT = re.compile(
    rf'(?m)^[ \t]*union\s*\{{\s*(?P<type>u32|unsigned\s+int)\s+(?P<word>{IDENT})\s*;'
    rf'\s*(?P<float>f32|float)\s+(?P<number>{IDENT})\s*;\s*}}\s*(?P<owner>{IDENT})\s*;'
)
_GOTO = re.compile(rf'\bgoto\s+({IDENT})\s*;')
_LABEL = re.compile(rf'\b({IDENT})\s*:(?!:)')
_MUTATION = r'(?:=(?!=)|[+*/%&|^-]=|<<=|>>=|\+\+|--)'


def _entry_witness(rows, offset):
    for index, (_, target, candidate) in enumerate(rows[:60]):
        expected, actual = _LOAD.fullmatch(target), _LOAD.fullmatch(candidate)
        if (not expected or not actual or expected.groups()[1:] != actual.groups()[1:] or expected[3] == '$sp'
                or integer(expected[2]) != offset or expected[1] == actual[1]):
            continue
        for _, target, candidate in rows[index + 1:index + 9]:
            expect_store, actual_store = _STORE.fullmatch(target), _STORE.fullmatch(candidate)
            if (expect_store and actual_store and expect_store[2] == actual_store[2]
                    and expect_store[1] == expected[1] and actual_store[1] == actual[1]):
                yield expected[1], actual[1], expect_store[2]


def _spill_reload_witness(rows, offset):
    for target_reg, candidate_reg, slot in _entry_witness(rows, offset):
        reload = f'lw {target_reg}, {slot}($sp)'
        instances = 0
        for index, (_, target, candidate) in enumerate(rows):
            actual = _LOAD.fullmatch(candidate)
            if target != reload or not actual or actual.groups()[1:] != (slot, '$sp') or actual[1] == target_reg:
                continue
            for _, following_target, following_candidate in rows[index + 1:index + 4]:
                a, b = _LOAD.fullmatch(following_target), _LOAD.fullmatch(following_candidate)
                if (a and b and a.groups()[:2] == b.groups()[:2] and a[3] == target_reg
                        and b[3] == actual[1] == b[1]):
                    instances += 1
                    break
        if instances >= 2 and candidate_reg != target_reg:
            return True
    return False


def _pointer_edits(part, read, macros):
    local = read['local']
    clean = part.clean
    signature = clean[clean.rfind('}', 0, part.opening) + 1:part.opening]
    if (block_path(part, read.start()) != [part.opening] or re.search(r'\bgoto\b', clean[part.opening:read.start()])
            or not re.search(rf'[(,]\s*void\s*\*\s*{read["param"]}\s*[,)]', signature)
            or not re.search(rf'(?m)^[ \t]*void\s*\*\s*{local}\s*;', clean[part.opening:read.start()])
            or len(re.findall(rf'\b{local}\b', part.body)) != 3
            or macros & {local, read['param'], 'char', 'u32'}):
        return None
    for start in _STRUCT.finditer(clean, part.opening + 1, read.start()):
        prefix = clean[part.opening:start.start()].rstrip()
        if block_path(part, start.start()) != [part.opening] or prefix[-1:] not in ('{', '}', ';'):
            continue
        end = close(clean, start.end() - 1, '{', '}')
        if not end or end >= read.start():
            continue
        owner = re.match(rf'\s*(?P<frame>{IDENT})\s*;', clean[end:read.start()])
        tail = _TAIL.search(clean, start.end(), end - 1)
        if not owner or not tail:
            continue
        frame, field = owner['frame'], tail['member']
        if macros & {frame, field, tail['pad']} or re.search(rf'\b{tail["pad"]}\b', clean[end:part.end]):
            continue
        member = rf'\b{frame}\s*\.\s*{field}\b'
        assign = re.compile(rf'(?m)^[ \t]*{member}\s*=\s*{local}\s*;[ \t]*\n')
        writes = list(assign.finditer(clean, read.end(), part.end))
        occurrences = list(re.finditer(rf'\b{frame}\b', clean[end:part.end]))
        if (len(writes) != 1 or block_path(part, writes[0].start()) != [part.opening]
                or re.search(r'[{}]|\bgoto\b', clean[read.end():writes[0].start()])
                or any(not re.match(r'\s*\.', clean[end + hit.end():part.end]) for hit in occurrences[1:])):
            continue
        uses = list(re.finditer(member, clean[part.opening + 1:part.end]))
        if not 4 <= len(uses) <= 12:
            continue
        start_pos = part.opening + 1
        copy = writes[0]
        if any(start_pos + use.start() < copy.start() for use in uses):
            continue
        if (re.search(rf'(?<!&)&(?!&)\s*\(*\s*{member}', part.body)
                or re.search(rf'{member}\s*(?:\)\s*)*{_MUTATION}'
                             rf'|(?:\+\+|--)\s*\(*\s*{member}', clean[copy.end():part.end])):
            continue
        replacements = [(start_pos + use.start(), start_pos + use.end(), local) for use in uses
                        if start_pos + use.start() >= copy.end()]
        return (frame, clean[start.end():tail.start()]), [(*tail.span(), ''), (*copy.span(), ''), *replacements]
    return None


def _zero_phase(part, word, param):
    owner, bits, number = word['owner'], word['word'], word['number']
    clean = part.clean
    if clean[part.opening:word.start()].rstrip()[-1:] not in ('{', '}', ';'):
        return None
    if re.search(rf'\b{IDENT}\s+\**\s*{param}\s*[,;=\[]', part.body):
        return None
    field = rf'{owner}\s*\.\s*{bits}'
    value = rf'\({word["type"]}\)\s*{param}\s*&\s*~\s*\({word["type"]}\)\s*{param}'
    initial = re.compile(rf'(?m)^[ \t]*{field}\s*=\s*{value}\s*;')
    matches = list(initial.finditer(clean, word.end(), part.end))
    if len(matches) != 1:
        return None
    init = matches[0]
    opened = re.match(rf'\s*(?:{IDENT}(?:\s*\.\s*{IDENT})?\s*=\s*0\.0[fF]\s*;\s*){{0,3}}\{{',
                      clean[init.end():part.end])
    if not opened:
        return None
    opening = init.end() + opened.end() - 1
    stop = close(clean, opening, '{', '}')
    if not stop:
        return None
    region = clean[opening:stop]
    outside = clean[part.opening + 1:opening] + clean[stop:part.end]
    escapes = set(_GOTO.findall(outside)).intersection(_LABEL.findall(region))
    if escapes or re.search(r'\bgoto\s*\*', part.body):
        return None
    switches = {opening + hit.end() - 1 for hit in re.finditer(r'\bswitch\s*\([^;{}]+\)\s*{', region)}
    if any(not switches.intersection(block_path(part, opening + hit.start()))
           for hit in re.finditer(r'\b(?:default|case\s+[^:;{}]+)\s*:', region)):
        return None
    if _escaped(part.body, owner) or _escaped(part.body, param):
        return None
    for use in re.compile(rf'\b{owner}\b').finditer(clean, part.opening + 1, part.end):
        if word.start() <= use.start() < word.end() or init.start() <= use.start() < init.end():
            continue
        if not opening < use.start() < stop:
            return None
        suffix = clean[use.end():stop]
        if re.match(rf'\s*\.\s*{bits}\s*=\s*0\s*;', suffix):
            continue
        if (not re.match(rf'\s*\.\s*{number}\b(?!\s*(?:\)\s*)*{_MUTATION})', suffix)
                or re.search(r'(?:\+\+|--)\s*\(*\s*$', clean[opening:use.start()])):
            return None
    return init.end(), opening, stop


def _zero_calls(part, context, word, param, frame, rows, macros):
    phase = _zero_phase(part, word, param)
    if not phase or macros & {word['owner'], word['type'], word['word'], word['float'], word['number']}:
        return []
    init_end, opening, stop = phase
    matched = Counter()
    for i, (_, target, candidate) in enumerate(rows[:-1]):
        if target != candidate or not (call := _CALL.fullmatch(target)):
            continue
        before = []
        for row in reversed(rows[max(0, i - 6):i]):
            if _CALL.fullmatch(row[1]):
                break
            before.append(row)
        if any(row[1:] == ('move $a1, $zero',) * 2 for row in (*before, rows[i + 1])):
            matched[call[1]] += 1
    by_call = {}
    for hit in re.finditer(rf'(?m)^[ \t]*(?P<callee>{IDENT})\(\s*{param}\s*,\s*(?P<zero>0)\s*\)\s*;',
                           part.clean[opening:stop]):
        by_call.setdefault(hit['callee'], []).append(hit)
    result = []
    for callee, calls in by_call.items():
        if callee in macros or not 4 <= len(calls) <= min(8, matched[callee]):
            continue
        kinds = set(re.findall(rf'\b{callee}\s*\(\s*void\s*\*\s*(?:{IDENT}\s*)?,\s*'
                               rf'(s32|int)(?:\s+{IDENT})?\s*\)\s*;', context))
        if len(kinds) != 1 or kinds & macros:
            continue
        kind = kinds.pop()
        replacement = f"({kind}) {word['owner']}.{word['word']}"
        changes = [(opening + call.start('zero'), opening + call.end('zero'), replacement) for call in calls]
        result.append(changes)
        # A stack reset immediately after the common zero can share its
        # floating view when the target stores the saved GPR directly.
        if reset := _first_reset(part, word, frame, init_end, opening, rows, macros):
            result.append([*changes, reset])
    return result


def _first_reset(part, word, frame, init_end, opening, rows, macros):
    owner, fields = frame
    first = re.match(rf'\s*{owner}\s*\.\s*(?P<field>{IDENT})\s*=\s*(?P<zero>0\.0[fF])\s*;',
                     part.clean[init_end:opening])
    if not first or first['field'] in macros:
        return None
    if not re.search(rf'(?m)^[ \t]*(?:volatile\s+)?{word["float"]}\s+{first["field"]}\s*;', fields):
        return None
    for index, (_, target, _) in enumerate(rows[:-1]):
        if not (move := re.fullmatch(r'move (\$s[0-7]|\$fp), \$zero', target)):
            continue
        for _, target, candidate in rows[index + 1:index + 5]:
            expected, actual = _STORE.fullmatch(target), _STORE.fullmatch(candidate)
            if expected and actual and expected[1] == move[1] and actual.groups() == ('$zero', expected[2]):
                return init_end + first.start('zero'), init_end + first.end('zero'), f"{word['owner']}.{word['number']}"
    return None


def variants(source, name, rows, header='', max_bytes=65536):
    if not rows or not any(row[1] != row[2] and row[1].startswith('lw ') for row in rows[:60]):
        return []
    visible = _visible(source, name, header)
    if not visible:
        return []
    part, context = visible
    macros = set(re.findall(rf'(?m)^\s*#\s*(?:define|undef)\s+({IDENT})', context))
    for read in _POINTER_READ.finditer(part.clean, part.opening + 1, part.end):
        if not _spill_reload_witness(rows, integer(read['offset'])):
            continue
        pointer = _pointer_edits(part, read, macros)
        if pointer is None:
            continue
        frame, edits = pointer
        result = []
        for word in _WORD_FLOAT.finditer(part.clean, part.opening + 1, part.end):
            for calls in _zero_calls(part, context, word, read['param'], frame, rows, macros):
                trial = edit(source, [*edits, *calls])
                if len(trial.encode()) <= max_bytes:
                    result.append((FAMILY, trial))
        return result[:4]
    return []
