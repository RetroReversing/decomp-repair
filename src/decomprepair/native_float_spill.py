"""Recover a natural single-precision spill and keep its late reset in the saved word."""

import re
from collections import Counter

from .call_lifetime_repairs import block_path
from .compiler_phase_repairs import fresh
from .integer_repair_support import IDENT, edit, integer
from .measured_staged_float_order import _plain_scalar, split_field_updates
from .natural_pointer_spill import _POINTER_READ, _WORD_FLOAT
from .operand_lifetime_repairs import _escaped, _visible
from .pattern_repairs import close

FAMILY = 'native_float_spill'
SETUP_COPY = 'native_float_setup_copy'
_LOAD = re.compile(r'lwc1 (\$f\d+), (0x[\da-f]+)\(\$sp\)')
_STORE = re.compile(r'swc1 (\$f\d+), (0x[\da-f]+)\((\$\w+)\)')
_POINTER_SLOT = re.compile(r'lw (\$t\d+), (0x[\da-f]+)\((\$s\d+)\)')
_START = re.compile(
    rf'(?m)^(?P<pad>[ \t]*)\{{[ \t]*\n'
    rf'[ \t]*(?P<kind>f32|float)\s+(?P<x>{IDENT})\s*;[ \t]*\n'
    rf'[ \t]*(?P<owner>{IDENT})\.(?P<bits>{IDENT})\s*=\s*'
    rf'(?P<zero>\((?P<word>u32|unsigned\s+int)\)\s*(?P<arg>{IDENT})\s*&\s*~\((?P=word)\)\s*(?P=arg))\s*;[ \t]*\n'
    rf'[ \t]*(?P<setup>{IDENT})\(\(\s*(?P<record>{IDENT})\.(?P<member>{IDENT})\s*=\s*'
    rf'(?P<view>(?P=owner)\.(?P<number>{IDENT}))\s*,\s*(?P<global>{IDENT})\s*=\s*(?P=view)\s*,\s*(?P=arg)\s*\)\)\s*;[ \t]*\n'
    rf'[ \t]*(?P=x)\s*=\s*0\.0f\s*;[ \t]*\n'
    rf'[ \t]*(?P<y>{IDENT})\s*=\s*(?P=view)\s*;[ \t]*\n'
    rf'[ \t]*(?P<z>{IDENT})\s*=\s*0\.0f\s*;[ \t]*\n'
)

_SAVED = r'\$(?:s[0-7]|fp)'
_SETUP_COPY = re.compile(
    rf'(?m)^[ \t]*(?P<owner>{IDENT})\.(?P<bits>{IDENT})\s*=\s*'
    rf'\((?P<word>u32|unsigned\s+int)\)\s*(?P<arg>{IDENT})\s*&\s*~\((?P=word)\)\s*(?P=arg)\s*;[ \t]*\n'
    rf'[ \t]*\{{[ \t]*\n[ \t]*(?P<kind>float|f32)\s+(?P<x>{IDENT})\s*=\s*0\.0f\s*;[ \t]*\n'
    rf'[ \t]*(?P<speed>{IDENT})\s*=\s*(?P<view>(?P=owner)\.(?P<number>{IDENT}))\s*;[ \t]*\n'
    rf'[ \t]*(?P<global>{IDENT})\s*=\s*0\.0f\s*;[ \t]*\n'
    rf'(?P<copy>(?P<pad>[ \t]*)(?P<y>{IDENT})\s*=\s*0\.0f\s*;[ \t]*\n)'
    rf'[ \t]*(?P<z>{IDENT})\s*=\s*0\.0f\s*;[ \t]*\n'
    rf'[ \t]*(?P<setup>{IDENT})\(\s*(?P=arg)\s*\)\s*;[ \t]*\n'
    rf'(?=[ \t]*if\s*\()'
)


def _setup_copy_witnesses(rows):
    reloads = Counter(hit[2] for _, target, candidate in rows
                      if target == candidate and (hit := _LOAD.fullmatch(target)) and hit[1] == '$f16')
    for i, (_, target, candidate) in enumerate(rows[4:-5], 4):
        call = re.fullmatch(rf'jal ({IDENT})', target) if target == candidate else None
        if not call:
            continue
        store = re.fullmatch(rf'sw ({_SAVED}), (0x[\da-f]+)\(\$sp\)', rows[i - 3][1])
        if not store or reloads[store[2]] < 2 or rows[i - 3][1] != rows[i - 3][2]:
            continue
        copied = re.fullmatch(rf'move ({_SAVED}), {re.escape(store[1])}', rows[i + 4][1])
        other = re.fullmatch(rf'move ({_SAVED}), ({_SAVED})', rows[i + 4][2])
        global_store = re.fullmatch(rf'sw {re.escape(store[1])}, %lo\(({IDENT})\)\(\$at\)', rows[i - 1][1])
        if (copied and other and copied[1] != other[1] and other[2] != store[1] and global_store
                and rows[i + 3][1] == rows[i + 3][2] and rows[i + 3][1].startswith('lbu $v0, ')
                and any(a == b == f'move {store[1]}, $zero' for _, a, b in rows[max(0, i - 7):i - 3])):
            yield call[1], global_store[1]


def setup_copy_variants(source, name, rows, header='', max_bytes=65536):
    witnesses = set(_setup_copy_witnesses(rows))
    visible = _visible(source, name, header) if witnesses else None
    if not visible:
        return []
    part, context = visible
    macros = set(re.findall(rf'(?m)^\s*#\s*(?:define|undef)\s+({IDENT})', context))
    signature = part.clean[part.clean.rfind('}', 0, part.opening) + 1:part.opening]
    if (any(' '.join(typ.split()) != 'float' for typ in re.findall(r'\btypedef\s+([^;{}]+?)\s+f32\s*;', context))
            or any(' '.join(typ.split()) != 'unsigned int'
                   for typ in re.findall(r'\btypedef\s+([^;{}]+?)\s+u32\s*;', context))):
        return []
    for hit in _SETUP_COPY.finditer(part.clean, part.opening + 1, part.end):
        names = {hit[key] for key in ('owner', 'arg', 'x', 'y', 'z', 'global', 'speed')}
        if (len(names) != 7 or (hit['setup'], hit['global']) not in witnesses
                or macros & set(re.findall(IDENT, hit[0]))
                or any(_escaped(part.body, hit[key]) for key in ('owner', 'arg', 'y'))
                or not _plain_scalar(part, hit['y'], hit['kind'], hit.start())
                or not re.search(rf'[(,]\s*void\s*\*\s*{hit["arg"]}\s*[,)]', signature)
                or re.search(rf'\b{IDENT}\s+\**\s*{hit["arg"]}\s*[,;=\[]', part.body)):
            continue
        expected = tuple(hit[key] for key in ('owner', 'bits', 'number', 'kind', 'word'))
        declarations = [decl for decl in _WORD_FLOAT.finditer(part.clean, part.opening + 1, hit.start())
                        if tuple(decl[key] for key in ('owner', 'word', 'number', 'float', 'type')) == expected]
        if (len(declarations) != 1 or block_path(part, declarations[0].start()) != [part.opening]
                or len(re.findall(rf'\}}\s*{hit["owner"]}\b', part.body)) != 1):
            continue
        raw = f'{hit["owner"]}.{hit["bits"]}'
        pad = hit['pad']
        insert = f'{pad}{raw} = ({raw} >> 16) << 16;\n{pad}{hit["y"]} = {hit["view"]};\n'
        trial = edit(source, [(*hit.span('copy'), ''), (hit.end(), hit.end(), insert)])
        if len(trial.encode()) <= max_bytes:
            return [(SETUP_COPY, trial)]
    return []


def _stack_reload_witnesses(rows):
    counts = Counter()
    for i, (_, target, candidate) in enumerate(rows):
        a, b = _LOAD.fullmatch(target), _LOAD.fullmatch(candidate)
        if not a or not b or a[1] != '$f16' or a[1] == b[1] or a[2] != b[2]:
            continue
        for _, target, candidate in rows[i + 1:i + 4]:
            lhs, rhs = _STORE.fullmatch(target), _STORE.fullmatch(candidate)
            if (lhs and rhs and lhs[1] == a[1] and rhs[1] == b[1]
                    and lhs.groups()[1:] == rhs.groups()[1:] and lhs[3] != '$sp'):
                counts[(a[2], int(lhs[2], 16))] += 1
                break
    return {(slot, field) for (slot, field), count in counts.items() if count >= 2}


def _matched_reset_slot(rows, symbol, reloads):
    global_store = re.compile(rf'sw (\$(?:s[0-7]|fp)), %lo\({symbol}\)\(\$\w+\)')
    slots = {slot for slot, _ in reloads}
    for i, (_, target, candidate) in enumerate(rows[:-1]):
        store = global_store.fullmatch(target) if target == candidate else None
        if store and any(rows[i + 1][1:] == (f'sw {store[1]}, {slot}($sp)',) * 2 for slot in slots):
            return True
    return False


def _pointer_declaration(part, setup, rows):
    offsets = {int(m[2], 16) for i, (_, target, candidate) in enumerate(rows[:60])
               if target == candidate and (m := _POINTER_SLOT.fullmatch(target))
               and any(a == b and re.fullmatch(rf'sw {re.escape(m[1])}, 0x[\da-f]+\(\$sp\)', a)
                       for _, a, b in rows[i + 1:i + 8])}
    for read in _POINTER_READ.finditer(part.clean, part.opening + 1, setup.start()):
        if (read['param'] != setup['arg'] or integer(read['offset']) not in offsets
                or block_path(part, read.start()) != [part.opening]):
            continue
        decl = list(re.compile(rf'(?m)^[ \t]*void\s*\*\s*{read["local"]}\s*;').finditer(
            part.clean, part.opening + 1, read.start(),
        ))
        if len(decl) == 1 and block_path(part, decl[0].start()) == [part.opening]:
            return decl[0].start()
    return None


def _frame_tail(part, setup, macros):
    record, member, kind = (setup[key] for key in ('record', 'member', 'kind'))
    for start in re.compile(r'(?m)^[ \t]*struct\s*\{').finditer(part.clean, part.opening + 1, setup.start()):
        end = close(part.clean, start.end() - 1, '{', '}')
        if not end or block_path(part, start.start()) != [part.opening]:
            continue
        declaration = re.match(rf'\s*{record}\s*;', part.clean[end:setup.start()])
        if not declaration or part.clean[part.opening:start.start()].rstrip()[-1:] not in ('{', '}', ';'):
            continue
        tail = re.compile(
            rf'(?m)^[ \t]*(?:u32|unsigned\s+int)\s+(?P<unused>{IDENT})\s*\[\s*2\s*\]\s*;[ \t]*\n'
            rf'[ \t]*volatile\s+{kind}\s+{member}\s*;[ \t]*\n(?=\s*$)'
        ).search(part.clean, start.end(), end - 1)
        if (not tail or tail['unused'] in macros or re.search(rf'\b{tail["unused"]}\b', part.clean[end:part.end])
                or len(re.findall(rf'\}}\s*{record}\b', part.body)) != 1):
            continue
        after = end + declaration.end()
        if re.search(rf'\b{record}\b(?!\s*\.)', part.clean[after:part.end]):
            continue
        return tail
    return None


def _reset_sites(part, setup, slot, macros):
    late_pattern = (
        rf'(?m)^[ \t]*{setup["owner"]}\.{setup["bits"]}\s*=\s*{re.escape(setup["zero"])}\s*;[ \t]*\n'
        rf'[ \t]*{setup["global"]}\s*=\s*{setup["view"]}\s*;[ \t]*\n'
        rf'(?P<insert>[ \t]*){slot}\s*=\s*{setup["view"]}\s*;[ \t]*\n'
    )
    late = list(re.compile(late_pattern).finditer(part.clean, setup.end(), part.end))
    if len(late) != 1 or macros & {setup['arg'], setup['record'], setup['member']}:
        return None
    if re.search(rf'(?<!&)&(?!&)\s*\(*\s*{slot}\b', part.body):
        return None
    uses = list(re.compile(rf'\b{slot}\b').finditer(part.clean, part.opening + 1, part.end))
    if len(uses) != 7 or any(hit.start() < setup.start() for hit in uses):
        return None
    assignments = [hit for hit in uses if re.match(r'\s*=(?!=)', part.clean[hit.end():part.end])]
    if len(assignments) != 4 or any(
        not setup.start() <= hit.start() < setup.end() and not late[0].start() <= hit.start() < late[0].end()
        and not re.match(r'\s*=\s*0\.0f\s*;', part.clean[hit.end():part.end])
        for hit in assignments
    ):
        return None
    return late[0], uses


def _scalar_copies(part, setup, slot, uses, writeback, fields):
    copies = re.compile(
        rf'[ \t]*\*\(\({setup["kind"]}\s*\*\)\s*\(\(\(char\s*\*\)\s*{setup["arg"]}\)\s*'
        rf'\+\s*(0x[\da-fA-F]+)\)\)\s*=\s*{slot}\s*;[ \t]*'
    )
    matched = 0
    for hit in uses:
        if writeback[0] <= hit.start() < writeback[1] or re.match(r'\s*=(?!=)', part.clean[hit.end():part.end]):
            continue
        start = part.clean.rfind('\n', part.opening, hit.start()) + 1
        end = part.clean.find('\n', hit.end(), part.end)
        copy = copies.fullmatch(part.clean, start, end)
        if not copy or int(copy[1], 16) not in fields:
            return False
        matched += 1
    return matched == 2


def _writeback_edits(source, part, setup, local, macros, fields):
    key = f'{setup["record"]}.{setup["member"]}'
    operand_order = (setup['x'], setup['y'], setup['z'], setup['global'], key, setup['view'])
    for reads, additions, stores in split_field_updates(part, macros):
        if len(reads) != len(operand_order) or reads[0].start() < setup.end():
            continue
        by_value = {add['delta']: (read, add) for read, add in zip(reads, additions, strict=True)}
        if by_value.keys() != set(operand_order) or set(operand_order).intersection(macros):
            continue
        if int(by_value[key][0]['offset'], 16) not in fields or reads[0]['base'] != setup['arg']:
            continue
        spans = [source[by_value[op][0].start():by_value[op][1].end()] for op in operand_order]
        update = ''.join(spans).replace(key, local)
        by_result = {hit['local']: hit for hit in stores}
        store_spans = []
        for operand in operand_order:
            store = by_result[by_value[operand][0]['local']]
            store_spans.append(source[store.start():store.end()])
        # The scheduler uses store order to break ties between independent updates.
        return [
            (reads[0].start(), stores[-1].end(), update + ''.join(store_spans[index] for index in order))
            for order in ((5, 4, 1, 0, 2, 3), (5, 4, 0, 1, 3, 2))
        ]
    return []


def variants(source, name, rows, header='', max_bytes=65536):
    reloads = _stack_reload_witnesses(rows)
    visible = _visible(source, name, header) if reloads else None
    if not visible:
        return []
    part, context = visible
    fields = {field for _, field in reloads}
    macros = set(re.findall(rf'(?m)^\s*#\s*(?:define|undef)\s+({IDENT})', context))
    if (re.search(r'(?m)^\s*#\s*pragma\s+STDC\s+FENV_ACCESS\s+ON', context)
            or any(' '.join(kind.split()) != 'float'
                   for kind in re.findall(r'\btypedef\s+([^;{}]+?)\s+f32\s*;', context))):
        return []
    signature = part.clean[part.clean.rfind('}', 0, part.opening) + 1:part.opening]
    for setup in _START.finditer(part.clean, part.opening + 1, part.end):
        if (macros & set(re.findall(IDENT, setup[0]))
                or not _matched_reset_slot(rows, setup['global'], reloads)
                or not re.search(rf'[(,]\s*void\s*\*\s*{setup["arg"]}\s*[,)]', signature)
                or re.search(rf'\b{IDENT}\s+\**\s*{setup["arg"]}\s*[,;=\[]', part.body)
                or len(re.findall(rf'(?m)^[ \t]*extern\s+{setup["kind"]}\s+{setup["global"]}\s*;', context)) != 1
                or len(re.findall(rf'\b(?:f32|float)\s+{setup["global"]}\b', context)) != 1
                or not all(_plain_scalar(part, setup[key], setup['kind'], setup.start()) for key in ('y', 'z'))
                or _escaped(part.body, setup['owner']) or _escaped(part.body, setup['x'])
                or _escaped(part.body, setup['arg']) or len({setup[key] for key in ('x', 'y', 'z')}) != 3):
            continue
        expected = tuple(setup[key] for key in ('owner', 'bits', 'number', 'kind', 'word'))
        declarations = [hit for hit in _WORD_FLOAT.finditer(part.clean, part.opening + 1, setup.start())
                        if tuple(hit[key] for key in ('owner', 'word', 'number', 'float', 'type')) == expected]
        if (len(declarations) != 1 or block_path(part, declarations[0].start()) != [part.opening]
                or part.clean[part.opening:declarations[0].start()].rstrip()[-1:] not in ('{', '}', ';')
                or len(re.findall(rf'\}}\s*{setup["owner"]}\b', part.body)) != 1):
            continue
        pointer = _pointer_declaration(part, setup, rows)
        frame_tail = _frame_tail(part, setup, macros)
        slot = re.escape(f'{setup["record"]}.{setup["member"]}')
        sites = _reset_sites(part, setup, slot, macros)
        if pointer is None or not frame_tail or not sites:
            continue
        pad = setup['pad']
        local = fresh(source, header, 'speed_delta')
        late, uses = sites
        writebacks = _writeback_edits(source, part, setup, local, macros, fields)
        if not writebacks or not _scalar_copies(part, setup, slot, uses, writebacks[0], fields):
            continue
        before = f'{pad}{setup["owner"]}.{setup["bits"]} = {setup["zero"]};\n{pad}{{\n'
        before += f'{pad}{setup["kind"]} {setup["x"]} = 0.0f;\n{pad}{local} = {setup["view"]};\n'
        before += f'{pad}{setup["global"]} = 0.0f;\n{pad}{setup["y"]} = 0.0f;\n{pad}{setup["z"]} = 0.0f;\n'
        before += f'{pad}{setup["setup"]}({setup["arg"]});\n'
        raw = f'{setup["owner"]}.{setup["bits"]}'
        initialize = (*setup.span(), before)
        # The value is already zero. A new word definition keeps CSE from
        # replacing the float source with the equivalent just-stored global.
        # The later combine pass removes the shift pair on that known zero.
        redefine = (late.start('insert'), late.start('insert'), f'{late["insert"]}{raw} = ({raw} >> 16) << 16;\n')
        separate = [(pointer, pointer, f'  {setup["kind"]} {local};\n'), (*frame_tail.span(), '')]
        writeback_start, writeback_end, _ = writebacks[0]
        accesses = [(*hit.span(), local) for hit in uses
                    if not setup.start() <= hit.start() < setup.end()
                    and not writeback_start <= hit.start() < writeback_end]
        trials = [edit(source, [*separate, initialize, redefine, writeback, *accesses])
                  for writeback in writebacks]
        allowed = [(FAMILY, trial) for trial in trials if len(trial.encode()) <= max_bytes]
        if allowed:
            return allowed
    return []
