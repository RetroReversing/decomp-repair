"""Move byte or halfword narrowing to the use sites indicated by KMC's instruction order."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, view

FAMILY = 'measured_narrow_use'
REG = r'\$\w+'
MASK8 = re.compile(rf'andi {REG}, ({REG}), (?:0xff|255)')
MASK16 = re.compile(r'andi \$v0, \$v0, (?:0xffff|65535)')
SIGNED = r'(?:s32|int)'
WORD = rf'(?:{SIGNED}|u32|unsigned\s+int)'
INLINE = re.compile(rf'\b(?:inline\s+static|static\s+inline)\s+u8\s+({IDENT})\s*\(')


def _byte_uses(source, part, rows):
    target_registers = [m[1] for _, target, _ in rows if (m := MASK8.fullmatch(target))]
    if (len(target_registers) == len(set(target_registers))
            or not any(not candidate and MASK8.fullmatch(target) for _, target, candidate in rows)):
        return []
    for definition in INLINE.finditer(part.clean, 0, part.opening):
        helper_name = definition[1]
        if not re.search(rf'\b{helper_name}\s*\(', part.body):
            continue
        helper = view(source, helper_name)
        args = re.match(rf'\s*[^()]*?,\s*{WORD}\s+({IDENT})\s*\)', part.clean[definition.end():part.opening])
        if not helper or not args:
            continue
        parameter = args[1]
        assigned = re.search(rf'(?<=[;{{}}])\s*(?P<name>{IDENT})\s*=\s*(?P<cast>\(\s*u8\s*\)\s*){parameter}\s*;',
                             helper.clean[helper.opening:helper.end])
        if not assigned:
            continue
        name = assigned['name']
        if not re.search(rf'(?<=[;{{}}])\s*{WORD}\s+{name}\s*;', helper.clean[helper.opening:helper.opening + assigned.start()]):
            continue
        indexed = re.search(rf'\b{IDENT}\s*\[\s*(?P<use>{name})\s*\]', helper.body)
        compared = re.search(rf'\bif\s*\(\s*{IDENT}\s*==\s*(?P<use>{name})\s*\)', helper.body)
        if (not indexed or not compared or len(re.findall(rf'\b{name}\b', helper.body)) != 4
                or min(indexed.start(), compared.start()) < assigned.end() - 1):
            continue
        offset = helper.opening + 1
        edits = [(helper.opening + assigned.start('cast'), helper.opening + assigned.end('cast'), '')]
        edits += [(offset + m.start('use'), offset + m.end('use'), f'(u8){name}') for m in (indexed, compared)]
        return [(FAMILY, edit(source, edits))]
    return []


def _remainder(source, part, rows):
    target, candidate = ([op for row in rows if (op := row[index])] for index in (1, 2))
    if not (any(MASK8.fullmatch(a) and MASK16.fullmatch(b) for a, b in zip(target, target[1:]))
            and any(MASK16.fullmatch(a) and MASK8.fullmatch(b) for a, b in zip(candidate, candidate[1:]))):
        return []
    pattern = re.compile(
        rf'(?<=[;{{}}])\s*(?P<var>{IDENT})\s*=\s*{IDENT}\s*\(\s*\)(?P<mask>\s*&\s*(?:0[xX][fF]{{4}}|65535))\s*;'
        rf'\s*(?P=var)\s*=\s*(?P<use>(?P=var))\s*%'
    )
    for hit in pattern.finditer(part.clean, part.opening, part.end):
        var = hit['var']
        if (not re.search(rf'(?<=[;{{}}])\s*{SIGNED}\s+{var}\s*;', part.clean[part.opening:hit.start()])
                or re.search(rf'&\s*\(*\s*{var}\b', part.body)):
            continue
        return [(FAMILY, edit(source, [(*hit.span('mask'), ''), (*hit.span('use'), f'(u16){var}')]))]
    return []


def _zero_store_width(source, name, rows):
    """Narrow a leaf's sole casted zero store when its address code already matches."""
    changes = [(wanted, current) for mark, wanted, current in rows if mark != ' ']
    if len(changes) != 1:
        return []
    wanted, current = changes[0]
    address = rf'\$zero, (?:0|0x0)?\((?P<base>{REG})\)'
    store = re.fullmatch(rf's(?P<width>[bh]) {address}', wanted)
    word = re.fullmatch(rf'sw {address}', current)
    if not store or not word or store['base'] != word['base'] or not (part := view(source, name)):
        return []
    statement = re.fullmatch(
        rf'\s*\*\(\s*(?P<type>[su]32)\s*\*\s*\)\s*'
        rf'\(\(\s*{IDENT}\s*\*\s*{NUMBER}\s*\)\s*\+\s*{IDENT}\s*\)\s*=\s*0\s*;\s*',
        part.body.rstrip('}\n '),
    )
    if not statement:
        return []
    start, end = statement.span('type')
    offset = part.opening + 1
    kind = 'u8' if store['width'] == 'b' else 'u16'
    return [('measured_zero_store_width', edit(source, [(offset + start, offset + end, kind)]))]


def _stage_masked_halfword_or(source, name, rows):
    """Stage a halfword mask before the same value is merged and stored."""
    changes = [i for i, (mark, _, _) in enumerate(rows) if mark != ' ']
    if len(changes) != 1 or (i := changes[0]) < 3 or i + 2 >= len(rows):
        return []
    a, b = (re.fullmatch(rf'or ({REG}), ({REG}), (\$a[0-3])', rows[i][1]),
            re.fullmatch(rf'or ({REG}), (\$a[0-3]), ({REG})', rows[i][2]))
    if not a or not b or a.groups() != (b[1], b[3], b[2]):
        return []
    mask = re.fullmatch(rf'andi {re.escape(a[2])}, {re.escape(a[2])}, ({NUMBER})', rows[i - 1][1])
    load = re.fullmatch(rf'lhu {re.escape(a[2])}, ({NUMBER})\(({REG})\)', rows[i - 3][1])
    store = re.fullmatch(rf'sh {re.escape(a[1])}, ({NUMBER})\(({REG})\)', rows[i + 2][1])
    if not mask or not load or not store or load.groups() != store.groups():
        return []
    if not (part := view(source, name)) or re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return []
    pattern = (
        rf', (?P<temp>{IDENT}) = (?P<expr>\((?P<field>M2C_FIELD\({IDENT}, u16 \*, (?P<offset>{NUMBER})\))'
        rf' & (?P<mask>{NUMBER})\) \| (?P<arg>{IDENT})), (?P=field) = (?P=temp),'
    )
    edits = []
    for hit in re.finditer(pattern, part.body):
        if integer(hit['offset']) != integer(load[1]) or integer(hit['mask']) != integer(mask[1]):
            continue
        if not re.search(rf'\bu16 {hit["temp"]};', part.body):
            continue
        if not re.search(rf'\bu16 {hit["arg"]}\s*(?=[,)])', part.clean[:part.opening]):
            continue
        start, end = (part.opening + 1 + pos for pos in hit.span('expr'))
        if source[start:end] != hit['expr']:
            continue
        text = f'{hit["field"]} & {hit["mask"]}, {hit["temp"]} |= {hit["arg"]}'
        edits.append((start, end, text))
    return [('measured_masked_halfword_or', edit(source, edits))] if len(edits) == 1 else []


def variants(source, name, rows):
    """Offer narrowing repairs separately so the next diff can guide the search."""
    if candidate := _zero_store_width(source, name, rows):
        return candidate
    if candidate := _stage_masked_halfword_or(source, name, rows):
        return candidate
    if not any('andi ' in row[1] for row in rows):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:goto|asm|__asm__)\b', _blank(source)):
        return []
    return _byte_uses(source, part, rows) + _remainder(source, part, rows)


HALFWORD_INDEX = 'shared_halfword_index'


def _halfword_index_callees(rows):
    """Find two halfword-index calls with a common target carrier and different candidate carriers."""
    masked = re.compile(rf'andi (?P<dst>{REG}), \$v0, 0xffff')
    calls = {}
    for call, delay, mask, scale, add, load in zip(rows, rows[1:], rows[2:], rows[3:], rows[4:], rows[5:]):
        callee = re.fullmatch(rf'jal ({IDENT})', call[1])
        target, candidate = (masked.fullmatch(op) for op in mask[1:])
        if (not callee or call[1] != call[2] or delay[1] != delay[2] or not target or not candidate
                or target['dst'] == candidate['dst'] or add[1] != add[2]):
            continue
        if (scale[1] != f'sll $v0, {target["dst"]}, 1' or scale[2] != f'sll $v0, {candidate["dst"]}, 1'
                or not all(re.fullmatch(rf'lh {REG}, \(\$v0\)', op) for op in load[1:])):
            continue
        key = callee[1], target['dst']
        calls.setdefault(key, set()).add(candidate['dst'])
    return {callee for (callee, _), carriers in calls.items() if len(carriers) >= 2}


def shared_halfword_index_variants(source, name, rows):
    """Reuse a narrowed call result across two score loops and inline the second load."""
    callees = _halfword_index_callees(rows)
    if not callees or not (part := view(source, name)) or re.search(r'\bvolatile\b', part.body):
        return []
    access = rf'{IDENT}\s*\.\s*(?P<field>{IDENT})'
    first = re.compile(
        rf'\bdo\s*{{\s*(?P<decl>u16\s+)(?P<slot>{IDENT})\s*=\s*'
        rf'(?P<callee>{IDENT})\s*\(\s*\(u16\)\s*(?P<i>{IDENT})\s*\)\s*;'
        rf'\s*(?P<score>{IDENT})\s*=\s*(?P<table>{access})\s*\[\s*(?P=slot)\s*\]\s*;'
        rf'\s*if\s*\(\s*(?P<best>{IDENT})\s*<\s*(?P=score)\s*\)\s*{{'
        rf'\s*(?P=best)\s*=\s*(?P=score)\s*;\s*{IDENT}\s*=\s*(?P=slot)\s*;\s*}}'
        rf'\s*(?P=i)\+\+\s*;\s*}}\s*while\s*\(\s*(?P=i)\s*<\s*{IDENT}\s*\)\s*;'
    )
    results = []
    for loop in first.finditer(part.clean, part.opening + 1, part.end):
        call, i, score, table, slot = (loop[key] for key in ('callee', 'i', 'score', 'table', 'slot'))
        if call not in callees or not re.search(rf'\bs16\s*\*\s*{loop["field"]}\s*;', part.body):
            continue
        second = re.compile(
            rf'\bdo\s*{{\s*(?P<index>{IDENT})\s*=\s*\(u16\)\s*{call}\s*\(\s*\(u16\)\s*{i}\s*\)\s*;'
            rf'(?P<load>\s*{score}\s*=\s*(?P<read>{re.escape(table)}\s*\[\s*(?P=index)\s*\])\s*;)'
            rf'\s*{i}\+\+\s*;\s*{loop["best"]}\s*\+=\s*'
            rf'(?P<compare>\*\s*(?P<ptr>{IDENT})\s*==\s*{score})\s*;'
            rf'\s*}}\s*while\s*\(\s*{i}\s*<\s*{IDENT}\s*\)\s*;'
        ).search(part.clean, loop.end(), part.end)
        if not second:
            continue
        index, ptr = second['index'], second['ptr']
        if len({index, i, score, slot}) != 4 or not re.search(rf'\bs16\s*\*\s*{ptr}\s*;', part.body):
            continue
        grouped = re.match(rf'\s*s32\s+(?P<names>{IDENT}(?:\s*,\s*{IDENT})+)\s*;',
                           part.clean[part.opening+1:loop.start()])
        if not grouped:
            continue
        names = re.findall(IDENT, grouped['names'])
        if ({index, i, score, loop['best']} - set(names) or slot in names
                or re.search(rf'&\s*\(*\s*(?:{index}|{i}|{score})\b', part.body)):
            continue
        if re.search(rf'\b(?:{index}|{score})\b', part.clean[second.end():part.end]):
            continue
        if re.search(rf'\b{index}\b', part.clean[loop.start():loop.end()]):
            continue
        if re.search(rf'\b{index}\b', part.clean[loop.end():second.start()]):
            continue
        start, end = (part.opening + 1 + p for p in grouped.span('names'))
        decl_end = part.opening + 1 + grouped.end()
        # Keep the score in the same scope while giving it its own declaration.
        replacement = ', '.join(n for n in names if n != score)
        comparison = f'{second["read"]} == *{ptr}'
        edits = [(start, end, replacement), (decl_end, decl_end, f' s32 {score};'),
                 (*loop.span('decl'), ''), (*second.span('load'), ''), (*second.span('compare'), comparison)]
        edits.extend((hit.start(), hit.end(), index) for hit in
                     re.compile(rf'\b{slot}\b').finditer(part.clean, loop.start(), loop.end()))
        lhs_end = part.clean.index('=', loop.end('slot'), loop.end())
        edits.append((lhs_end + 1, lhs_end + 1, ' (u16)'))
        if all(source[a:b] == part.clean[a:b] for a, b, _ in edits):
            results.append((HALFWORD_INDEX, edit(source, edits)))
    return results[:2]


BYTE_BACKEDGE = 'byte_backedge_carrier'


def _byte_backedge_evidence(rows):
    """A byte load feeds the loop branch and its delay-slot mask in both builds."""
    load = re.compile(rf'lbu (?P<dst>{REG}), (?P<address>(?:0x[0-9a-f]+|\d+)?\({REG}\))')
    branch = re.compile(rf'bne (?P<byte>{REG}), (?P<sentinel>{REG}), (?P<edge>\S+)')
    for read, jump, narrow in zip(rows, rows[1:], rows[2:]):
        target, candidate = (load.fullmatch(op) for op in read[1:])
        if (not target or not candidate or target['dst'] == candidate['dst']
                or target['address'] != candidate['address']):
            continue
        first, second = (branch.fullmatch(op) for op in jump[1:])
        if (first and second and first['byte'] == target['dst'] and second['byte'] == candidate['dst']
                and first['sentinel'] == second['sentinel'] and first['edge'] == second['edge']
                and (a := MASK8.fullmatch(narrow[1])) and (b := MASK8.fullmatch(narrow[2]))
                and a[1] == target['dst'] and b[1] == candidate['dst']
                and narrow[1] == narrow[2].replace(f', {candidate["dst"]},', f', {target["dst"]},', 1)):
            return True
    return False


def byte_backedge_variants(source, name, rows):
    """Try reusing the byte carrier from the guarded loop entry at its back edge."""
    from .loaded_byte_repairs import declarators
    from .pattern_repairs import close

    if not _byte_backedge_evidence(rows) or not (part := view(source, name)):
        return []
    byte_mask = r'(?:255|0[xX][fF]{2})'
    entry = re.compile(
        rf'(?<=[;{{}}])\s*(?P<old>{IDENT})\s*=\s*\*\s*(?P<ptr>{IDENT})\s*;'
        rf'\s*if\s*\(\s*\(\s*\(u8\)\s*(?P=old)\s*\)\s*!=\s*(?P<stop>\d+)\s*\)\s*{{'
        rf'\s*(?P<opcode>{IDENT})\s*=\s*(?P=old)\s*&\s*{byte_mask}\s*;\s*do\s*{{'
    )
    result = []
    for hit in entry.finditer(part.clean, part.opening + 1, part.end):
        old, ptr, opcode = (hit[k] for k in ('old', 'ptr', 'opcode'))
        end = close(part.clean, hit.end() - 1, '{', '}')
        if not end or not re.search(rf'(?<=[;{{}}])\s*u8\s*\*\s*{ptr}\s*(?:=|;)', part.clean[:hit.start()]):
            continue
        tail = re.search(
            rf'(?<=[;{{}}])\s*(?P<phase>{IDENT})\s*=\s*\*\s*{ptr}\s*;'
            rf'\s*{opcode}\s*=\s*(?P=phase)\s*&\s*{byte_mask}\s*;\s*}}\s*$',
            part.clean[hit.end():end],
        )
        if not tail:
            continue
        phase = tail['phase']
        latch = re.match(rf'\s*while\s*\(\s*(?P<phase>{phase})\s*!=\s*{hit["stop"]}\s*\)\s*;',
                         part.clean[end:part.end])
        if not latch or len({old, ptr, opcode, phase}) != 4:
            continue
        declarations = {old: r'(?:long|s32|int|u32)', phase: WORD}
        if not all(re.search(rf'(?<=[;{{}}])\s*{typ}\s+{var}\s*;', part.clean[:hit.start()])
                   and len(declarators(part.clean, var)) == 1 for var, typ in declarations.items()):
            continue
        if (len(re.findall(rf'\b{phase}\b', part.body)) != 4
                or re.search(rf'\b{old}\b', part.clean[end + latch.end():part.end])
                or re.search(rf'&\s*\(*\s*{old}\b', part.body)
                or len(declarators(part.clean, ptr)) != 1):
            continue
        loop_body = part.clean[hit.end():end]
        jumps = set(re.findall(rf'\bgoto\s+({IDENT})\s*;', loop_body))
        labels = set(re.findall(rf'(?m)^[ \t]*({IDENT})[ \t]*:', loop_body))
        if jumps - labels or re.search(r'\b(?:asm|__asm__)\b', loop_body):
            continue
        edits = [(m.start(), m.end(), old) for m in re.compile(rf'\b{phase}\b').finditer(
            part.clean, hit.end() + tail.start(), end + latch.end())]
        result.append((BYTE_BACKEDGE, edit(source, edits)))
    return result[:4]


BOOLEAN_BYTE = 'boolean_byte_carrier'


def _boolean_byte_evidence(rows):
    boolean = re.compile(rf'(?:sltu ({REG}), \$zero, {REG}|sltiu ({REG}), {REG}, 1)')
    for compare, copy in zip(rows, rows[1:]):
        if compare[1] != compare[2] or not (test := boolean.fullmatch(compare[1])):
            continue
        reg = test[1] or test[2]
        move = re.fullmatch(rf'move ({REG}), {re.escape(reg)}', copy[1])
        if move and copy[2] == f'andi {move[1]}, {reg}, 0xff':
            return True
    return False


def boolean_byte_carriers(source, name, rows):
    """Give a comparison result a byte local when the target copies it without a mask."""
    from .integer_repair_support import locals_for

    if not _boolean_byte_evidence(rows) or not (part := view(source, name)):
        return []
    pattern = re.compile(
        rf'(?<=[;{{}}])\s*(?P<value>{IDENT})\s*=\s*[^;{{}}?:=!<>]+(?:==|!=)\s*(?:0x[0-9a-fA-F]+|\d+)\s*;'
        rf'\s*(?P<flag>{IDENT})\s*=\s*(?P<cast>\(\s*u8\s*\)\s*)(?P=value)\s*;'
    )
    words = {decl['name']: decl for decl in locals_for(part) if decl['type'] == 's32'}
    result = []
    for match in pattern.finditer(part.clean, part.opening + 1, part.end):
        flag, value = match['flag'], match['value']
        decl = words.get(flag)
        if not decl or value == flag or value not in words or decl.end() > match.start():
            continue
        uses = re.findall(rf'\b{flag}\b', part.body)
        resets = re.findall(rf'(?<=[;{{}}])\s*{flag}\s*=\s*0\s*;', part.body)
        tests = re.findall(rf'\b{flag}\s*&\s*(?:0[xX][fF]{{2}}|255)\b', part.body)
        if len(resets) != 1 or not tests or len(uses) != 3 + len(tests):
            continue
        # The declared byte still only receives zero or a comparison result.
        start, end = match.span('cast')
        if source[start:end] == match['cast']:
            result.append((BOOLEAN_BYTE, edit(source, [(*decl.span('type'), 'u8'), (start, end, '')])))
    return result[:4]
