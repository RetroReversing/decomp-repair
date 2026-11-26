"""Recover measured KMC record reads and the calls that consume their values."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_SNAPSHOT = re.compile(
    r'lw \$a0, (?P<flags>\d+)\(\$v0\)\n'
    rf'lui \$v1, %hi\((?P<callback>{IDENT})\)\naddiu \$v1, \$v1, %lo\((?P=callback)\)\n'
    rf'lui \$at, %hi\((?P<shared>{IDENT})\)\nsw \$v0, %lo\((?P=shared)\)\(\$at\)\n'
    r'sw \$v1, (?P<hook>\d+)\(\$v0\)\nori \$a0, \$a0, (?P<mask>\d+)\nsw \$a0, (?P=flags)\(\$v0\)'
)
_SNAPSHOT_SOURCE = re.compile(
    rf'(?P<publish>M2C_FIELD\(&(?P<owner>{IDENT}), void \*\*, (?P<shared>{NUMBER})\) = (?P<obj>{IDENT});)'
    rf'\s*M2C_FIELD\((?P=obj), M2C_UNK \*\*, (?P<hook>{NUMBER})\) = &(?P<callback>{IDENT});'
    rf'\s*M2C_FIELD\((?P=obj), s32 \*, (?P<flags>{NUMBER})\) = \(s32\) '
    rf'\((?P<read>M2C_FIELD\((?P=obj), s32 \*, (?P=flags)\)) \| (?P<mask>{NUMBER})\);'
)
_TABLE = re.compile(
    rf'lui \$v1, %hi\((?P<index>{IDENT})\)\nlbu \$v1, %lo\((?P=index)\)\(\$v1\)\n'
    r'(?:addiu \$sp, \$sp, -\d+\nsw \$ra, \d+\(\$sp\)\n)?'
    r'sll \$v0, \$v1, (?P<lead>\d+)\naddu \$v0, \$v0, \$v1\nsll \$v0, \$v0, (?P<tail>\d+)\n'
    rf'lui \$a1, %hi\((?P<table>{IDENT})\)\naddu \$a1, \$a1, \$v0\nlhu \$a1, %lo\((?P=table)\)\(\$a1\)\n'
    rf'jal (?P<call>{IDENT})\naddiu \$a0, \$zero, (?P<argument>\d+)'
)
_TABLE_SOURCE = re.compile(
    rf'\b(?P<call>{IDENT})\((?P<argument>{NUMBER}), \*\(&(?P<obj>{IDENT}) \+ (?P<table>{NUMBER}) \+ '
    rf'\(M2C_FIELD\(&(?P=obj), u8 \*, (?P<index>{NUMBER})\) \* (?P<stride>{NUMBER})\)\)\);'
)
_PASS = re.compile(
    r'sltu \$a2, \$zero, \$v0\nsrl \$v0, \$a0, 8\nandi \$v0, \$v0, 3\nbne \$v0, \$v1, \d+\n'
    r'move \$a1, \$a2\nandi \$v0, \$a0, 15\nxor \$v0, \$v0, \$a3\nsltu \$v0, \$zero, \$v0\n'
    r'negu \$v0, \$v0\nand \$a1, \$a2, \$v0\nandi \$v0, \$a1, 255\nbnez \$v0, \d+\nnop\n'
    rf'lui \$at, %hi\((?P<field>{IDENT})\)\nsb \$zero, %lo\((?P=field)\)\(\$at\)\n'
    rf'jal (?P<call>{IDENT})\nnop\njal (?P<next>{IDENT})\nnop'
)
_PASS_SOURCE = re.compile(
    rf'if \(!\((?P<value>{IDENT}) & 0xFF\)\) \{{\s*'
    rf'M2C_FIELD\(&(?P<owner>{IDENT}), s8 \*, (?P<field>{NUMBER})\) = 0;\s*'
    rf'(?P<call>{IDENT})\((?P<args>M2C_FIELD\(&{IDENT}, u32 \*, {NUMBER}\), (?P=value), {IDENT}, {IDENT})\);'
    rf'\s*(?P<next>{IDENT})\(\);\s*\}}'
)
_ARM_LOAD = re.compile(r'lw \$v0, (\d+)\(\$(v0|a0)\)')
_ARM_SOURCE = re.compile(
    rf'if \((?P<bits>{IDENT}) & (?P<mask>{NUMBER})\) \{{\s*'
    rf'(?P<out>{IDENT}) \|= M2C_FIELD\(\((?P<global>{IDENT}) \+ '
    rf'\((?P<index>{IDENT}|\({IDENT} & 0xFF\)) \* (?P<stride>{NUMBER})\)\), s32 \*, (?P<field>{NUMBER})\);\s*\}}'
)


def variants(source, name, header, rows, resolve=None):
    if not 29 <= len(rows) <= 196:
        return []
    changed = [row for row in rows if row[0] != ' ']
    if len(changed) not in (8, 10, 12, 26):
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    if (resolve and len(changed) == 10 and (witness := _SNAPSHOT.search(target))
            and ('o', '', f'lui $at, %hi({witness["shared"]})') in changed
            and ('o', f'lui $at, %hi({witness["shared"]})', '') in changed):
        family, build, evidence = 'measured_pre_publish_field_read', _snapshot, witness
    elif (resolve and len(changed) == 12 and len(tables := list(_TABLE.finditer(target))) == 4
          and _scaled_table_changes(changed, tables)):
        family, build, evidence = 'measured_byte_stride_halfword_calls', _typed_tables, tables
    elif (resolve and len(changed) == 8 and (witness := _PASS.search(target))
            and any(not left and right == 'move $a2, $t0' for _, left, right in changed)):
        family, build, evidence = 'measured_drop_inferred_guarded_call_args', _drop_args, witness
    elif len(changed) == 26 and (fields := _arm_fields(changed)):
        family, build, evidence = 'measured_guarded_record_bases', _arm_bases, fields
    else:
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    fixed = build(part, name, header, resolve, evidence)
    return [(family, fixed)] if fixed else []


def _snapshot(part, _name, header, resolve, target):
    local = '__repair_pre_publish_flags'
    match = _SNAPSHOT_SOURCE.search(part.body)
    if not match or local in part.source or local in header or match['callback'] != target['callback']:
        return None
    owner = resolve(match['owner'])
    if owner is None or owner + integer(match['shared']) != resolve(target['shared']):
        return None
    if any(integer(match[key]) != int(target[key]) for key in ('flags', 'hook', 'mask')):
        return None
    start = part.opening + 1
    return edit(part.source, [
        (start, start, f'\n    s32 {local};'),
        (start + match.start(), start + match.start(), f'{local} = {match["read"]};\n    '),
        (start + match.start('read'), start + match.end('read'), local),
    ])


def _scaled_table_changes(changed, tables):
    for i, inst in enumerate(tables):
        shift, upper, lower = list(changed[3 * i:3 * i + 3])
        old = re.fullmatch(rf'lui \$a1, %hi\(({IDENT})\)', upper[2])
        tail = int(inst['tail'])
        if (not old or normalized_integer_lines(shift[1:]) != (f'sll $v0, $v0, {tail}', f'sll $v0, $v0, {tail + 2}')
                or upper[1] != f'lui $a1, %hi({inst["table"]})'
                or lower[1:] != (f'lhu $a1, %lo({inst["table"]})($a1)', f'lhu $a1, %lo({old[1]})($a1)')):
            return False
    return True


def _typed_tables(part, _name, header, resolve, targets):
    first = targets[0]
    start_symbol, table_symbol = first['index'], first['table']
    start, table = resolve(start_symbol), resolve(table_symbol)
    if start is None or table is None or start == table:
        return None
    if any(re.search(rf'\b{symbol}\b', part.clean + _blank(header)) for symbol in (start_symbol, table_symbol)):
        return None
    lookups = list(_TABLE_SOURCE.finditer(part.body))
    if len(lookups) != len(targets):
        return None
    edits = []
    body_start = part.opening + 1
    for hit, inst in zip(lookups, targets):
        addr = resolve(hit['obj'])
        lead, tail = int(inst['lead']), int(inst['tail'])
        index = resolve(inst['index'])
        if (addr is None or index is None or index != addr + integer(hit['index'])
                or not 0 <= lead < 8 or not 0 <= tail < 8 or addr + integer(hit['table']) != table
                or inst['table'] != table_symbol or inst['call'] != hit['call']
                or integer(hit['argument']) != int(inst['argument'])
                or integer(hit['stride']) != (((1 << lead) + 1) << tail)):
            return None
        fixed = (f'{hit["call"]}({hit["argument"]}, '
                 f'M2C_FIELD({table_symbol}, u16 *, {start_symbol}[{index - start}] * {hit["stride"]}));')
        edits.append((body_start + hit.start(), body_start + hit.end(), fixed))
    if [resolve(inst['index']) for inst in targets] != list(range(start, start + len(targets))):
        return None
    declaration = part.source.rfind('\n', 0, part.opening) + 1
    if not re.match(r'void\s+', part.clean[declaration:part.opening]):
        return None
    edits.append((declaration, declaration, f'extern u8 {start_symbol}[];\nextern u8 {table_symbol}[];\n\n'))
    return edit(part.source, edits)


def _drop_args(part, name, header, resolve, target):
    hit = _PASS_SOURCE.search(part.body)
    callee = target['call']
    if not hit or hit['call'] != callee or hit['next'] != target['next'] or callee == name:
        return None
    addr = resolve(hit['owner'])
    if addr is None or addr + integer(hit['field']) != resolve(target['field']):
        return None
    decl = re.search(rf'(?m)^[ \t]*(?:M2C_UNK|s32|void)\s+{callee}\((?P<args>u32, s32, s32, s8)\);',
                     part.clean[:part.opening])
    if not decl or len(re.findall(rf'\b{callee}\b', part.clean)) != 2 or re.search(rf'\b{callee}\b', _blank(header)):
        return None
    start = part.opening + 1
    return edit(part.source, [(*decl.span('args'), 'void'),
                              (start + hit.start('args'), start + hit.end('args'), '')])


def _arm_fields(changed):
    target = []
    for add, load in zip(changed[::2], changed[1::2]):
        left, right = normalized_integer_lines(load[1:])
        if not (hit := _ARM_LOAD.fullmatch(left)):
            return None
        field, reg = hit.groups()
        old = 'v1' if reg == 'v0' else 'v0'
        expected = ('addu $v0, $v0, $v1', 'addu $v1, $v1, $v0') if reg == 'v0' else (
            'addu $a0, $a0, $v0', 'addu $v0, $v0, $a0',
        )
        if add[1:] != expected or right != f'lw $v0, {field}(${old})':
            return None
        target.append(int(field))
    return target


def _arm_bases(part, _name, header, _resolve, fields):
    local = '__repair_arm_base'
    arms = list(_ARM_SOURCE.finditer(part.body))
    if local in part.source or local in header or len(arms) != len(fields):
        return None
    first = arms[0]
    base, bits, output = first['global'], first['bits'], first['out']
    if not re.search(rf'\bextern s32 {base};', part.clean[:part.opening]):
        return None
    if any((arm['global'], arm['bits'], arm['out']) != (base, bits, output)
           or integer(arm['field']) != field or integer(arm['stride']) != 56 for arm, field in zip(arms, fields)):
        return None
    head = re.search(
        rf'if \({bits} & 1\) \{{\s*(?P<old>{IDENT}) = \(char \*\)\(\({base} \+ '
        rf'\((?P<index>{IDENT}) \* (?P<stride>{NUMBER})\)\)\);\s*'
        rf'{output} = M2C_FIELD\((?P=old), s32 \*, (?P<field>{NUMBER})\);\s*\}}', part.body)
    if not head or integer(head['stride']) != 56 or len(re.findall(rf'\b{head["old"]}\b', part.body)) != 3:
        return None
    decl = re.search(rf'\bchar \*{head["old"]};', part.body[:head.start()])
    if not decl or head.end() > first.start():
        return None
    start = part.opening + 1
    changes = [(start + decl.start(), start + decl.end(), '')]
    for hit in (head, *arms):
        mask, op = ('1', '=') if hit is head else (hit['mask'], '|=')
        text = f'''if ({bits} & {mask}) {{
        s32 {local} = {base};
        {local} += {hit['index']} * {hit['stride']};
        {output} {op} M2C_FIELD({local}, s32 *, {hit['field']});
    }}'''
        changes.append((start + hit.start(), start + hit.end(), text))
    return edit(part.source, changes)
