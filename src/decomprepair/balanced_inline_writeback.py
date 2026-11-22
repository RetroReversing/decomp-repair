"""Pair a signed-byte countdown with an inline field-sum writeback."""

import re

from .balanced_selector_zero import _DECREMENT
from .balanced_signed_selector_increment import _HELPER
from .compiler_phase_repairs import fresh
from .csource import find
from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for, refs
from .operand_lifetime_repairs import _in_scope, _typed_locals, _visible
from .pattern_repairs import close

FAMILY = 'balanced_inline_field_writeback'
_FREG = r'\$f\d+'
_REG = r'\$[a-z][a-z0-9]*'
_SIGNED = re.compile(rf'lb \$v0, ({NUMBER})\(({_REG})\)')
_MTC = re.compile(rf'mtc1 {_REG}, \$f16')
_LOAD = re.compile(rf'lwc1 {_FREG}, ({NUMBER})\(({_REG})\)')
_STORE = re.compile(rf'swc1 {_FREG}, ({NUMBER})\(({_REG})\)')
_ADD = re.compile(rf'add\.s {_FREG}, {_FREG}, \$f16')
_FIELD = rf'\(f32\s*\*\)\s*\(\(\(char\s*\*\)\s*(?P<base>{IDENT})\)\s*\+\s*(?P<offset>{NUMBER})\)'
_SUM = re.compile(
    rf'(?m)^(?P<pad>[ \t]*)(?P<local>{IDENT})\s*=\s*'
    rf'\(f32\)\s*\(\(\*\((?P<address>{_FIELD})\)\)\s*\+\s*'
    rf'(?P<delta>{IDENT}(?:\s*\.\s*{IDENT})?)\s*\)\s*;[ \t]*\n'
)
_PUT = re.compile(rf'(?m)^[ \t]*\*\({_FIELD}\)\s*=\s*(?P<local>{IDENT})\s*;[ \t]*\n')


def _countdowns(linked):
    for index, (target, actual, _) in enumerate(linked[:-5]):
        load = _SIGNED.fullmatch(target)
        if not load or target != actual or not linked[index + 1][0].startswith('beqz $v0, '):
            continue
        if [r[:2] for r in linked[index + 2:index + 4]] != [
            ('move $v1, $v0', ''), ('addiu $v0, $v1, -1', 'addiu $v0, $v0, -1')
        ] or not linked[index + 4][0].startswith('j '):
            continue
        store = f'sb $v0, {load[1]}({load[2]})'
        if linked[index + 5][:2] == (store, store):
            yield index, integer(load[1])


def _witnesses(rows):
    linked = [(target, actual, i) for i, (_, target, actual) in enumerate(rows) if target]
    for count, offset in _countdowns(linked):
        for index in range(count + 35, min(len(linked) - 12, count + 140)):
            target, actual, original = linked[index]
            if not _MTC.fullmatch(target) or not _MTC.fullmatch(actual):
                continue
            stores = [_STORE.fullmatch(asm) for asm, _, _ in linked[index + 1:index + 3]]
            if not all(stores) or not _ADD.fullmatch(linked[index + 3][0]):
                continue
            upcoming = [line for _, _, line in rows[original + 1:original + 9] if line]
            if len(upcoming) < 2 or upcoming[0] != 'nop' or not _ADD.fullmatch(upcoming[1]):
                continue
            base = stores[0][2]
            if base == '$sp' or stores[1][2] != base:
                continue
            loads = {integer(op[1]) for asm, _, _ in linked[index - 19:index]
                     if (op := _LOAD.fullmatch(asm)) and op[2] == base}
            written = {integer(op[1]) for asm, _, _ in linked[index + 1:index + 9]
                       if (op := _STORE.fullmatch(asm)) and op[2] == base}
            if len(loads) == 6 and loads == written:
                yield offset, frozenset(loads)


def _run(pattern, source, position, count):
    items = []
    for _ in range(count):
        item = pattern.match(source, position)
        if not item:
            return []
        items.append(item)
        position = item.end()
    return items


def _float_delta(part, operation, floats, context):
    delta = operation['delta']
    if '.' not in delta:
        if delta in floats:
            return _in_scope(part, floats[delta][1], operation.start())
        declaration = rf'\bextern\s+(?:volatile\s+)?(?:f32|float)\s+{delta}\s*;'
        conflicting = rf'\b(?:int|short|char|double|void|u\d+|s\d+)\s*\**\s*{delta}\b'
        return bool(re.search(declaration, context) and not re.search(conflicting, part.body))
    owner, member = (token.strip() for token in delta.split('.'))
    candidates = []
    for record in re.finditer(r'\b(?:struct|union)\s*{', part.clean[part.opening:operation.start()]):
        opening = part.opening + record.end() - 1
        end = close(part.clean, opening, '{', '}')
        if (not end or not _in_scope(part, opening, operation.start())
                or not re.match(rf'\s*{owner}\s*;', part.clean[end:])):
            continue
        members = re.finditer(rf'\b(?:f32|float)\s+{member}\s*;', part.clean[opening + 1:end - 1])
        for match in members:
            prefix = part.clean[opening + 1:opening + 1 + match.start()]
            if prefix.count('{') == prefix.count('}'):
                candidates.append(opening)
    return len(candidates) == 1


def _writeback(part, count, offsets, floats, macros, context):
    limit = min(part.end, count.end() + 7000)
    for start in _SUM.finditer(part.clean, count.end(), limit):
        sums = _run(_SUM, part.clean, start.start(), len(offsets))
        if not sums:
            continue
        stores = _run(_PUT, part.clean, sums[-1].end(), len(offsets))
        if not stores:
            continue
        source_values = {(m['base'], integer(m['offset']), m['local']) for m in sums}
        stored_values = {(m['base'], integer(m['offset']), m['local']) for m in stores}
        if (source_values != stored_values or {entry[1] for entry in source_values} != offsets
                or len({entry[0] for entry in source_values}) != 1 or len({entry[2] for entry in source_values}) != 6):
            continue
        if any(m['local'] not in floats or not _in_scope(part, floats[m['local']][1], m.start())
               or macros & set(re.findall(IDENT, m[0])) for m in [*sums, *stores]):
            continue
        if not all(_float_delta(part, m, floats, context) for m in sums):
            continue
        yield sums


def variants(source, name, rows, *, header='', max_bytes=65536):
    witnesses = set(_witnesses(rows))
    visible = _visible(source, name, header) if witnesses else None
    if not visible or not (definition := find(source, name)):
        return []
    part, context = visible
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    if macros & {'f32', 's8', 'u8'} or re.search(r'(?m)^\s*#\s*pragma\s+STDC\s+FENV_ACCESS\s+ON', context):
        return []
    kinds = {'f32': {'float'}, 's8': {'signed char'}, 'u8': {'unsigned char'}}
    if any(' '.join(typ.split()) not in kinds[alias]
           for typ, alias in re.findall(r'\btypedef\s+([^;{}]+?)\s+(f32|s8|u8)\s*;', context)):
        return []
    ints = {decl['name']: decl for decl in locals_for(part)}
    floats = _typed_locals(part, r'(?:f32|float)')
    helpers = {match['fn'] for match in _HELPER.finditer(context)}
    helper = fresh(source, header, 'repair_shifted_float')
    pointer = fresh(source, header, 'repair_field')
    value = fresh(source, header, 'repair_delta')
    trials = []
    for countdown in _DECREMENT.finditer(part.clean, part.opening + 1, part.end):
        decl = ints.get(countdown['old'])
        if (not decl or decl['type'] not in {'s8', 'signed char', 'u8', 'unsigned char'} or countdown['helper'] not in helpers or len(refs(part, decl)) != 3
                or macros & set(re.findall(IDENT, countdown[0]))):
            continue
        byte_offset = integer(countdown['offset'])
        if byte_offset != integer(countdown['write_offset']):
            continue
        for offset, offsets in witnesses:
            if offset != byte_offset:
                continue
            for sums in _writeback(part, countdown, offsets, floats, macros, context):
                pad, field = countdown['pad'], countdown['field']
                decrement = f'{pad}if ({field} != 0)\n{pad}{{\n{pad}  ({field})--;\n{pad}}}'
                declaration = (
                    f'inline static f32 {helper}(f32 *{pointer}, f32 {value})\n'
                    f'{{\n  return *{pointer} + {value};\n}}\n\n'
                )
                start = definition[0]
                changes = [(*countdown.span(), decrement), (start, start, declaration)]
                changes.extend(
                    (*m.span(), f'{m["pad"]}{m["local"]} = {helper}({m["address"]}, {m["delta"]});\n')
                    for m in sums
                )
                trial = edit(source, changes)
                if len(trial.encode()) <= max_bytes:
                    trials.append((FAMILY, trial))
    return trials if len(trials) == 1 else []
