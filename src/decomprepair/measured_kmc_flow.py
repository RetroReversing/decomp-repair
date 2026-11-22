"""Recover source boundaries behind three small KMC scheduling differences."""

import re
import struct

from . import goto_structure_repairs
from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for, plain_repair_view, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_MOVE_LIMIT = re.compile(
    r'lh \$v0, (?P<src0>\d+)\(\$a1\)\nsll \$v0, \$v0, 1\nsh \$v0, \(\$a0\)\n'
    r'lh \$v0, (?P<src1>\d+)\(\$a1\)\naddiu \$a2, \$zero, (?P<literal>\d+)\n'
    r'sh \$a2, (?P<dst>\d+)\(\$a0\)\nsh \$zero, \d+\(\$a0\)\n'
    r'sll \$v0, \$v0, 1\nsh \$v0, 2\(\$a0\)'
)
_LIMIT_SOURCE = re.compile(
    rf'(?P<literal>\s*M2C_FIELD\((?P<dst>{IDENT}), s16 \*, (?P<field>{NUMBER})\) = (?P<value>{NUMBER});)'
    rf'(?P<coordinates>\s*M2C_FIELD\((?P=dst), s16 \*, 0\) = \(s16\) '
    rf'\(M2C_FIELD\((?P<src>{IDENT}), s16 \*, (?P<src0>{NUMBER})\) \* 2\);'
    rf'\s*M2C_FIELD\((?P=dst), s16 \*, 2\) = \(s16\) '
    rf'\(M2C_FIELD\((?P=src), s16 \*, (?P<src1>{NUMBER})\) \* 2\);)'
)
_RELOC_STORE = re.compile(rf'lui \$at, %hi\((?P<slot>{IDENT})\)\nsw \$v0, %lo\((?P=slot)\)\(\$at\)')

_FLOAT = re.compile(
    rf'lui \$at, %hi\((?P<first>{IDENT})\)\nldc1 \$f2, %lo\((?P=first)\)\(\$at\)\n'
    r'mtc1 \$a0, \$f0\nnop\ncvt\.d\.w \$f0, \$f0\nmul\.d \$f0, \$f0, \$f2\n'
    rf'lui \$at, %hi\((?P<second>{IDENT})\)\nldc1 \$f2, %lo\((?P=second)\)\(\$at\)\n'
    r'cvt\.s\.d \$f12, \$f0\ncvt\.d\.s \$f12, \$f12\nmul\.d \$f12, \$f12, \$f2\n'
    r'addiu \$sp, \$sp, -24\nsw \$ra, 16\(\$sp\)\n'
    rf'jal (?P<call>{IDENT})\ncvt\.s\.d \$f12, \$f12\nlui \$at, (?P<scale>\d+)\n'
    r'mtc1 \$at, \$f2\nnop\nmul\.s \$f12, \$f0, \$f2\ntrunc\.w\.s \$f0, \$f12\n'
    r'mfc1 \$v0, \$f0\nnop\nlw \$ra, 16\(\$sp\)\njr \$ra\naddiu \$sp, \$sp, 24'
)
_FLOAT_SOURCE = re.compile(
    rf'\s*return \(s32\) \((?P<call>{IDENT})\(\(f32\) '
    rf'\(\(f64\) \(f32\) \(\(f64\) (?P<arg>{IDENT}) \* (?P<first>{IDENT})\) \* (?P<second>{IDENT})\)\)'
    r' \* (?P<scale>\d{1,10}(?:\.\d{1,10})?[fF])\);\s*'
)

_STAGED_CALL = re.compile(
    r'lw \$v0, (?P<field>\d+)\(\$s2\)\naddiu \$a0, \$s1, (?P<arg>\d+)\nlw \$s0, \(\$v0\)\n'
    rf'jal (?P<call>{IDENT})\nmove \$a1, \$zero\naddu \$s0, \$s3, \$s0\n'
    r'lw \$v1, \d+\(\$s0\)\nsw \$v0, (?P<out>\d+)\(\$s0\)'
)
_CALL_SOURCE = re.compile(
    rf'(?P<lead>(?P<base>{IDENT}) = \*M2C_FIELD\({IDENT}, s32 \*\*, (?P<field>{NUMBER})\);)'
    rf'(?P<address>\s*(?P<addr>{IDENT}) = \(\({IDENT} & 0xFF\) \* 4\) \+ (?P=base);)'
    rf'(?P<store>\s*M2C_FIELD\((?P=addr), s32 \*, (?P<out>{NUMBER})\) = )'
    rf'(?P<call>{IDENT})\((?P<input>{IDENT}) \+ (?P<arg>{NUMBER}), 0\);'
)
_INDIRECT_CALL = re.compile(
    r'lw \$s0, (?P<field>\d+)\(\$s2\)\naddiu \$a1, \$zero, (?P<mode>\d+)\nmove \$a2, \$s5\n'
    r'lw \$v0, (?P<slot>\d+)\(\$s0\)\nsubu \$s3, \$s3, \$s1\njalr \$v0\nmove \$a0, \$s0'
)
_INDIRECT_SOURCE = re.compile(
    rf'(?P<update>(?P<left>{IDENT}) -= (?P<right>{IDENT});)(?P<gap>\s*)'
    rf'(?P<call>M2C_FIELD\((?P<base>{IDENT}), M2C_UNK \(\*\*\)\(void \*, M2C_UNK, s32\), '
    rf'(?P<slot>{NUMBER})\)\((?P=base), (?P<mode>{NUMBER}), {IDENT}\);)'
)


_GUARDED_STORE = re.compile(
    rf'(?m)^(?P<indent>[ \t]+)if \(\(\(s32\) (?P<key>{IDENT}) >= (?P<low>{NUMBER})\) && '
    rf'\(\((?P<value>{IDENT}) = (?P<first>{NUMBER}), \(\(\(s32\) (?P=key) < (?P<mid>{NUMBER})\) != 0\)\)'
    rf' \|\| \((?P=value) = (?P<second>{NUMBER}), \(\(\(s32\) (?P=key) < (?P<high>{NUMBER})\) != 0\)\)\)\) '
    rf'\{{\n[ \t]+(?P<field>M2C_FIELD\({IDENT}, s16 \*, (?P<offset>{NUMBER})\)) = (?P=value);\n(?P=indent)\}}'
)


def _guarded_constant_stores(source, name, rows):
    """Expose both stores so KMC can allocate the halfword value in the target register."""
    changes = [(mark, target, current) for mark, target, current in rows if mark != ' ']
    if not 3 <= len(changes) <= 8 or any(mark != 'r' for mark, _, _ in changes):
        return None
    if not (part := view(source, name)):
        return None
    hits = list(_GUARDED_STORE.finditer(part.clean, part.opening + 1, part.end))
    if len(hits) != 1:
        return None
    hit = hits[0]
    if not integer(hit['low']) < integer(hit['mid']) < integer(hit['high']):
        return None
    local = re.escape(hit['value'])
    declaration_pattern = re.compile(rf'(?m)^[ \t]*s16[ \t]+{local};[ \t]*\n')
    declarations = list(declaration_pattern.finditer(part.clean, part.opening + 1, hit.start()))
    if (len(declarations) != 1 or len(re.findall(rf'\b{local}\b', part.body)) != 4
            or re.search(r'/[*/]', source[hit.start():hit.end()])):
        return None
    stores = [store for _, op, _ in changes
              if (store := re.fullmatch(rf'sh (\$\w+), ({NUMBER})\(\$\w+\)', op))
              and integer(store[2]) == integer(hit['offset'])]
    if len(stores) != 1:
        return None
    loads = {integer(load[1]) for _, op, _ in changes if (load := re.fullmatch(
        rf'addiu {re.escape(stores[0][1])}, \$zero, ({NUMBER})', op))}
    if loads != {integer(hit['first']), integer(hit['second'])} or len(loads) != 2:
        return None
    indent, key, low, mid, high, field, first, second = (
        hit[key] for key in ('indent', 'key', 'low', 'mid', 'high', 'field', 'first', 'second'))
    declaration = declarations[0]
    if re.search(r'/[*/]', source[declaration.start():declaration.end()]):
        return None
    return edit(source, [(*declaration.span(), ''), (*hit.span(), (
        f'{indent}if ((s32) {key} >= {low}) {{\n'
        f'{indent}    if ((s32) {key} < {mid}) {{\n'
        f'{indent}        {field} = {first};\n'
        f'{indent}    }} else if ((s32) {key} < {high}) {{\n'
        f'{indent}        {field} = {second};\n'
        f'{indent}    }}\n'
        f'{indent}}}'))])


def _early_float_load(source, name, header, rows):
    """Stage the parent float immediately after loading the child pointer."""
    changes = [(i, left, right) for i, (mark, left, right) in enumerate(rows) if mark != ' ']
    if len(changes) != 4:
        return None
    (read_at, read, gap1), (_, sub, gap2), (_, gap3, late_read), (_, gap4, late_sub) = changes
    if read_at == 0 or any((gap1, gap2, gap3, gap4)) or (read, sub) != (late_read, late_sub):
        return None
    reg, slot = r'\$\w+', NUMBER
    load = re.fullmatch(rf'lwc1 (?P<value>\$f\d+), (?P<offset>{slot})\((?P<base>{reg})\)', read)
    if not load:
        return None
    value, base = re.escape(load['value']), re.escape(load['base'])
    bind = re.fullmatch(rf'lw (?P<child>{reg}), (?P<offset>{slot})\({base}\)', rows[read_at - 1][1])
    store_at = changes[-1][0] + 1
    if (not bind or store_at >= len(rows) or not re.fullmatch(rf'sub\.s {value}, {value}, \$f\d+', sub)):
        return None
    out = re.fullmatch(rf'swc1 {value}, ({slot})\({re.escape(bind["child"])}\)', rows[store_at][1])
    if (not out or bind['child'] == load['base'] or not (part := view(source, name))
            or '__repair_parent_float' in source + header):
        return None
    pattern = re.compile(
        rf'(?m)^(?P<indent>[ \t]+)(?P<child>{IDENT}) = M2C_FIELD\((?P<parent>{IDENT}), void \*\*, (?P<link>{slot})\);\n'
        rf'(?P<stores>(?:(?P=indent)M2C_FIELD\((?:(?P=parent)|(?P=child)), s(?:8|16|32) \*, {slot}\)'
        rf' = (?:{slot}|{IDENT});\n)+)'
        rf'(?P=indent)M2C_FIELD\((?P=child), f32 \*, (?P<out>{slot})\) = \(f32\) '
        rf'\((?P<read>M2C_FIELD\((?P=parent), f32 \*, (?P<in>{slot})\)) - \d+(?:\.\d+)?[fF]\);')
    hits = [hit for hit in pattern.finditer(part.clean, part.opening + 1, part.end)
            if tuple(integer(hit[key]) for key in ('link', 'out', 'in')) ==
            (integer(bind['offset']), integer(out[1]), integer(load['offset']))]
    if len(hits) != 1:
        return None
    hit = hits[0]
    if re.search(r'/[*/]', source[hit.start():hit.end()]):
        return None
    local = '__repair_parent_float'
    return edit(source, [
        (part.opening + 1, part.opening + 1, f'\n    f32 {local};'),
        (hit.start('stores'), hit.start('stores'), f'{hit["indent"]}{local} = {hit["read"]};\n'),
        (*hit.span('read'), local),
    ])


def _float_scale_carrier(source, name, rows):
    """Let the table value carry the product in both arms."""
    changes = [(target, current) for mark, target, current in rows if mark != ' ']
    if not 4 <= len(changes) <= 8 or any(mark not in (' ', 'r') for mark, _, _ in rows):
        return None
    loads = re.compile(rf'lwc1 (?P<reg>\$f\d+), (?P<address>%lo\((?P<table>{IDENT})\)\(\$\w+\))')
    tables = [match for target, current in changes if (match := loads.fullmatch(target))
              and (other := loads.fullmatch(current)) and match['address'] == other['address']
              and match['reg'] != other['reg']]
    if (len(tables) != 2 or tables[0].groups() != tables[1].groups()
            or not any(target.startswith('mul.s ') and current.startswith('mul.s ') for target, current in changes)
            or not (part := view(source, name))):
        return None
    table = tables[0]['table']
    if not re.search(rf'\bextern f32 {table}\[\];', part.clean[:part.opening]):
        return None
    pattern = re.compile(
        rf'(?m)^(?P<indent>[ \t]+)(?P<acc>{IDENT}) = (?P<load>{table}\[{IDENT}\]) \* (?P<factor>{IDENT});')
    top = list(pattern.finditer(part.clean, part.opening + 1, part.end))
    if len(top) != 2:
        return None
    first, second = top
    acc, factor, coeff = first['acc'], first['factor'], second['acc']
    if (second['factor'] != coeff or len({acc, factor, coeff}) != 3
            or any(not re.search(rf'(?m)^[ \t]*f32 {local};', part.body) for local in (acc, coeff))):
        return None
    tail = re.compile(rf'\n(?P<indent>[ \t]+){acc} = {coeff} \* {factor};')
    final = tail.match(part.clean, second.end())
    if not final or re.search(rf'\b{coeff}\b', part.clean[final.end():part.end]):
        return None
    return edit(source, [
        (*first.span(), f'{first["indent"]}{acc} = {first["load"]};\n{first["indent"]}{acc} *= {factor};'),
        (second.start(), final.end(), f'{second["indent"]}{acc} = {second["load"]};\n'
         f'{final["indent"]}{acc} *= {coeff};\n{final["indent"]}{acc} *= {factor};'),
    ])


def _byte_subtraction_carrier(source, name, rows):
    """Reuse the signed subtraction result in place of an unrelated pointer local."""
    changes = [(i, a, b) for i, (mark, a, b) in enumerate(rows) if mark != ' ']
    if not 3 <= len(changes) <= 14 or any(mark not in (' ', 'r') for mark, _, _ in rows):
        return None
    sub = re.compile(r'subu (\$\w+), (\$\w+), (\$\w+)')
    moved = [(i, want) for i, a, b in changes if (want := sub.fullmatch(a)) and sub.fullmatch(b)]
    if len(moved) != 1 or not (part := view(source, name)):
        return None
    pos, want = moved[0]
    if not any(op.startswith(f'bgez {want[1]}, ') for _, op, _ in rows[pos + 1:pos + 6]):
        return None
    load = re.compile(rf'lbu (\$\w+), ({NUMBER})\((\$\w+)\)')
    loads = {hit[1]: (integer(hit[2]), hit[3]) for _, op, _ in rows[max(pos - 12, 0):pos]
             if (hit := load.fullmatch(op))}
    if want[2] not in loads or want[3] not in loads or loads[want[2]][1] == loads[want[3]][1]:
        return None
    byte_read = r'\*\(\(u8 \*\) \(\(\(char \*\) {base}\) \+ {offset}\)\)'
    right = byte_read.format(base=rf'(?P<right_base>{IDENT})', offset=rf'(?P<right_offset>{NUMBER})')
    left = byte_read.format(base=rf'(?P<left_base>{IDENT})', offset=rf'(?P<left_offset>{NUMBER})')
    pattern = re.compile(
        rf'(?m)^(?P<indent>[ \t]+)(?P<result>{IDENT}) = (?P<right>{right});\n'
        rf'(?P=indent)(?P<pointer>{IDENT}) = \(void \*\) \((?P<left>{left})\);\s*'
        rf'(?P=result) = \(u32\) (?P=pointer) - (?P=result);')
    hits = [hit for hit in pattern.finditer(part.clean, part.opening + 1, part.end)
            if integer(hit['left_offset']) == loads[want[2]][0] and integer(hit['right_offset']) == loads[want[3]][0]]
    if len(hits) != 1:
        return None
    hit = hits[0]
    result, pointer = hit['result'], hit['pointer']
    if (len({result, pointer, hit['left_base'], hit['right_base']}) != 4
            or not re.search(rf'(?m)^[ \t]*(?:short|s16|s32) {result};', part.body)
            or not re.search(rf'(?m)^[ \t]*void \*{pointer};', part.body)
            or re.search(rf'\b{pointer}\b', part.clean[hit.end():part.end])
            or re.search(r'/[*/]', source[hit.start():hit.end()])):
        return None
    indent = hit['indent']
    return edit(source, [(*hit.span(), f'{indent}{result} = {hit["left"]};\n{indent}{result} -= {hit["right"]};')])


def _inline_interpolated_product(source, name, rows):
    """Keep an interpolation as the multiply operand when its result register differs."""
    add = re.compile(r'add\.s (\$f\d+), (\$f\d+), (\$f\d+)')
    mul = re.compile(r'mul\.s (\$f\d+), (\$f\d+), (\$f\d+)')
    witnesses = []
    for index, (a_mark, a_target, a_current) in enumerate(rows[:-1]):
        if a_mark != 'r':
            continue
        following = index + 1
        marker, branch, current = rows[following]
        # The multiply can be in the delay slot of a branch shared by both builds.
        if marker == ' ' and branch == current and branch.startswith(('beq ', 'bne ')):
            following += 1
        if following >= len(rows):
            continue
        m_mark, m_target, m_current = rows[following]
        if m_mark != 'r':
            continue
        a, b, c, d = [pattern.fullmatch(op) for pattern, op in
                      ((add, a_target), (add, a_current), (mul, m_target), (mul, m_current))]
        if (a and b and c and d and a.groups()[1:] == b.groups()[1:] and a[1] != b[1]
                and c.groups()[:2] == d.groups()[:2] and c[3] == a[1] and d[3] == b[1]):
            witnesses.append(a)
    if (len(witnesses) != 1 or any(mark not in (' ', 'r') for mark, _, _ in rows)
            or not (part := view(source, name))):
        return None
    table = rf'(?P<table>{IDENT})\[(?P<index>{IDENT})\]'
    interpolation = (rf'\(\s*\(\s*1\.0[fF]\s*-\s*(?P<mix>{IDENT})\s*\)\s*\*\s*{table}\s*'
                     r'\+\s*(?P=mix)\s*\*\s*(?P=table)\[(?P=index)\s*\+\s*1\]\s*\)')
    pattern = re.compile(
        rf'(?m)^(?P<indent>[ \t]+)(?P<temp>{IDENT})\s*=\s*(?P<blend>{interpolation});\n'
        rf'(?P=indent)(?P<dst>{IDENT})\s*=\s*(?P<gain>{IDENT})\s*\*\s*(?P=temp);')
    matches = list(pattern.finditer(part.clean, part.opening + 1, part.end))
    if len(matches) != 1:
        return None
    hit = matches[0]
    names = {hit['temp'], hit['dst'], hit['gain'], hit['mix']}
    floats = {var.strip() for decl in re.findall(rf'\bf32\s+({IDENT}(?:\s*,\s*{IDENT})*)\s*;', part.body)
              for var in decl.split(',')}
    if (len(names) != 4 or not names <= floats or re.search(r'/[*/]', source[hit.start():hit.end()])
            or not part.clean[:hit.start()].rstrip().endswith((';', '{', '}'))
            or re.search(rf'&\s*{hit["temp"]}\b|\bgoto\b|\bvolatile\s+f32', part.body)):
        return None
    # A later read must follow a fresh assignment whose block has not ended.
    tail = part.clean[hit.end():part.end]
    active = False
    scopes = []
    for token in re.finditer(rf'[{{}}]|\b{hit["temp"]}\b', tail):
        if token[0] == '{':
            scopes.append(active)
        elif token[0] == '}':
            active = scopes.pop() if scopes else False
        elif re.match(r'\s*=(?!=)', tail[token.end():]):
            active = tail[:token.start()].rstrip().endswith((';', '{', '}'))
        elif not active:
            return None
    return edit(source, [(*hit.span(), f'{hit["indent"]}{hit["dst"]} = {hit["gain"]}*{hit["blend"]};')])


def _collapse_identical_assignments(source, name, header, rows):
    """Remove redundant scalar control flow behind a candidate-only zero move."""
    if not any(not target and re.fullmatch(r'move \$\w+, \$zero', actual)
               for _, target, actual in rows) or not (part := view(source, name)):
        return []
    shape = re.compile(
        rf'(?m)^(?P<indent>[ \t]+)if\s*\((?P<test>{IDENT}(?:\s*\|\|\s*{IDENT})?)\)\s*\{{\s*'
        rf'(?P<wrapped>do\s*\{{\s*)?(?P<dst>{IDENT})\s*=\s*(?P<value>{NUMBER});'
        r'(?(wrapped)\s*\}\s*while\s*\(0\);)\s*\}\s*else\s*\{\s*'
        r'(?P=dst)\s*=\s*(?P=value);\s*\}')
    locals_ = set(re.findall(rf'(?m)^[ \t]*(?:register\s+)?(?:f32|[su](?:8|16|32))\s+({IDENT})\s*;', part.body))
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', part.clean + '\n' + header))
    edits = []
    for hit in shape.finditer(part.clean, part.opening + 1, part.end):
        names = set(re.findall(IDENT, hit['test'])) | {hit['dst']}
        if (names <= locals_ and not names & macros
                and not any(re.search(rf'\bvolatile\b[^;\n]*\b{name}\b\s*(?:[;=,])', part.body)
                            for name in names)
                and part.clean[:hit.start()].rstrip().endswith(('{', '}', ';'))
                and not re.search(r'/[*/]', source[hit.start():hit.end()])):
            edits.append((*hit.span(), f'{hit["indent"]}{hit["dst"]} = {hit["value"]};'))
    if not 1 <= len(edits) <= 3:
        return []
    groups = [edits, *([item] for item in edits)] if len(edits) > 1 else [edits]
    return [('measured_identical_branch_assignments', edit(source, group)) for group in groups]


_BYTE_GUARD_RETURN = re.compile(
    rf'\bif\s*\(\s*(?P<load>\*\s*\(\s*(?:u8|unsigned\s+char)\s*\*\s*\)'
    rf'\s*\(\s*\(\s*char\s*\*\s*\)\s*{IDENT}\s*\+\s*(?P<offset>{NUMBER})\s*\))'
    rf'\s*==\s*0\s*\)\s*return\s+(?P<comparison>{IDENT}\s*<=\s*'
    rf'\*\s*\(\s*(?:u8|unsigned\s+char)\s*\*\s*\)\s*'
    rf'\(\s*\(\s*char\s*\*\s*\)\s*{IDENT}\s*\+\s*{NUMBER}\s*\))\s*;'
    rf'\s*goto\s+(?P<label>{IDENT})\s*;(?=\s*\}}\s*$)'
)


def _byte_guard_return(source, name, header, rows):
    """Give KMC a separate register for a byte guard and its comparison."""
    changed = [(i, target, current) for i, (mark, target, current) in enumerate(rows) if mark != ' ']
    if len(changed) != 2 or any(rows[i][0] != 'r' for i, _, _ in changed):
        return None
    (i, new_load, load), (j, new_branch, branch) = changed
    if j != i + 1:
        return None
    field = re.fullmatch(rf'lbu \$v0, ({NUMBER}\(\$\w+\))', load)
    exit_target = re.fullmatch(rf'bnez \$v0, ({NUMBER})', branch)
    if not field or not exit_target:
        return None
    new_reg = re.fullmatch(r'lbu (\$(?!v0\b)\w+), ' + re.escape(field[1]), new_load)
    if not new_reg or new_branch != f'bnez {new_reg[1]}, {exit_target[1]}':
        return None
    part = view(source, name)
    if not part or not re.search(rf'\b(?:s32|int)\s+{re.escape(name)}\s*\([^{{}};]*\)\s*$',
                                 part.clean[:part.opening]):
        return None
    hit = _BYTE_GUARD_RETURN.search(part.clean, part.opening + 1, part.end)
    if not hit or integer(hit['offset']) != integer(field[1].split('(')[0]):
        return None
    label = hit['label']
    if not re.search(rf'(?<![\w:]){re.escape(label)}\s*:\s*return\s+0\s*;', part.body[:hit.start() - part.opening - 1]):
        return None
    local = '__repair_guard_result'
    if local in source or local in header or re.search(r'/[*/]', source[hit.start():hit.end()]):
        return None
    return edit(source, [(*hit.span(), (
        f'{{ int {local} = {hit["load"]}; if ({local} == 0) {local} = {hit["comparison"]}; '
        f'else goto {label}; return {local}; }}'
    ))])


_FLOAT_RANGES = re.compile(
    rf'\b(?P<x>{IDENT})\s*=\s*(?P<xmax>{IDENT})\s*-\s*(?P<xmin>{IDENT})\s*;\s*'
    rf'(?P<y>{IDENT})\s*=\s*(?P<ymax>{IDENT})\s*-\s*(?P<ymin>{IDENT})\s*;\s*'
    rf'if\s*\(\s*(?P=y)\s*<\s*(?P=x)\s*\)\s*\{{\s*'
    rf'do\s*\{{\s*(?P<out>{IDENT})\s*=\s*(?P=x)\s*;\s*\}}\s*while\s*\(0\)\s*;\s*\}}\s*'
    rf'else\s*\{{\s*(?P=out)\s*=\s*(?P=y)\s*;\s*\}}'
)


def _in_place_float_ranges(source, name, header, rows):
    """Reuse the two extrema locals when their computed widths feed one store."""
    changed = [(target, current) for mark, target, current in rows if mark != ' ']
    if len(changed) != 3 or any(mark not in (' ', 'r') for mark, _, _ in rows):
        return None
    target, current = zip(*changed)
    sub = re.fullmatch(r'sub\.s (\$f\d+), \1, (\$f\d+)', target[0])
    old = re.fullmatch(r'sub\.s (\$f\d+), (\$f\d+), (\$f\d+)', current[0])
    if not sub or not old or sub.groups() != old.groups()[1:] or old[1] == sub[1]:
        return None
    comparison = re.fullmatch(r'c\.lt\.s (\$f\d+), ' + re.escape(sub[1]), target[1])
    store = re.fullmatch(rf'swc1 {re.escape(sub[1])}, (?P<out>%lo\((?P<symbol>{IDENT})\)\(\$\w+\))', target[2])
    if (not comparison or not store or current[1] != f'c.lt.s {comparison[1]}, {old[1]}'
            or current[2] != f'swc1 {old[1]}, {store["out"]}'):
        return None
    part = plain_repair_view(source, name, header)
    if not part or not (hit := _FLOAT_RANGES.search(part.clean, part.opening + 1, part.end)):
        return None
    names = [hit[key] for key in ('x', 'y', 'xmax', 'ymax', 'xmin', 'ymin', 'out')]
    if len(set(names)) != len(names) or hit['out'] != store['symbol']:
        return None
    if re.search(r'/[*/]', source[hit.start():hit.end()]):
        return None
    prefix = part.clean[part.opening + 1:hit.start()]
    suffix = part.clean[hit.end():part.end]
    for local in names[:6]:
        if (not re.search(rf'\bf32\s+{local}\s*;', prefix)
                or re.search(rf'&\s*{local}\b', prefix) or re.search(rf'\b{local}\b', suffix)):
            return None
    _, _, xmax, ymax, xmin, ymin, out = names
    return edit(source, [(*hit.span(), (
        f'{xmax} -= {xmin};\n  {ymax} -= {ymin};\n  if ({ymax} < {xmax}) '
        f'{{ {out} = {xmax}; }} else {{ {out} = {ymax}; }}'
    ))])


_FLOAT_SUM_UPDATE = re.compile(rf'\b(?P<sum>{IDENT})[ \t]*\+=[ \t]*(?P<square>{IDENT})[ \t]*;')


def _float_sum_destination(source, name, header, rows):
    """Stage a final sum in the dead square local without changing operand order."""
    changes = [(target, current) for mark, target, current in rows if mark != ' ']
    if len(changes) != 5 or any(mark not in (' ', 'r') for mark, _, _ in rows):
        return None
    squares = []
    for target, current in changes[:3]:
        new = re.fullmatch(r'mul\.s (\$f\d+), (\$f\d+), \2', target)
        old = re.fullmatch(r'mul\.s (\$f\d+), (\$f\d+), \2', current)
        if not new or not old or new[2] != old[2] or new[1] == old[1]:
            return None
        squares.append((new[1], old[1]))
    (first, old_first), (second, old_second), (third, old_third) = squares
    if (len({first, second, third}) != 3 or (old_first, old_second, old_third) != (third, first, second)
            or first != '$f12' or changes[3:] != [
                (f'add.s {first}, {first}, {second}', f'add.s {first}, {first}, {third}'),
                (f'add.s {first}, {first}, {third}', f'add.s {first}, {first}, {second}'),
            ]):
        return None
    part = plain_repair_view(source, name, header)
    if not part:
        return None
    matches = list(_FLOAT_SUM_UPDATE.finditer(part.clean, part.opening + 1, part.end))
    if len(matches) != 1:
        return None
    hit = matches[0]
    total, square = hit['sum'], hit['square']
    if total == square or re.search(r'/[*/]', source[hit.start():hit.end()]):
        return None
    declarations = re.compile(rf'\bf32\s+{IDENT}(?:\s*,\s*{IDENT})*\s*;')
    locals_ = {local for decl in declarations.findall(part.body) for local in re.findall(IDENT, decl)[1:]}
    if not {total, square} <= locals_ or len(re.findall(rf'\b{square}\b', part.body)) != 3:
        return None
    prefix = part.clean[part.opening + 1:hit.start()]
    if not re.search(rf'\b{square}\s*=\s*({IDENT})\s*\*\s*\1\s*;', prefix):
        return None
    fixed = f'{{ {square} = {total} + {square}; {total} = {square}; }}'
    return edit(source, [(*hit.span(), fixed)])


_PACKED_CHANNELS = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<red>{IDENT})\s*=\s*\((?P<value>{IDENT})\s*>>\s*1\)\s*<<\s*16\s*;\s*'
    rf'(?P<blue>{IDENT})\s*=\s*\(255[Uu]?\s*-\s*(?P=value)\)\s*\|\s*64[Uu]?\s*;\s*'
    rf'(?P=value)\s*=\s*(?P=red)\s*\|\s*(?P<alpha>{IDENT})\s*;\s*'
    rf'(?P=alpha)\s*=\s*0x7[fF]800000[Uu]?\s*;\s*'
    rf'(?P=red)\s*>>=\s*1\s*;\s*(?P=value)\s*\|=\s*(?P=blue)\s*;\s*(?P=blue)\s*>>=\s*1\s*;\s*'
    rf'(?P<out>{IDENT})->{IDENT}\s*=\s*(?P=value)\s*;\s*'
    rf'(?P=out)->{IDENT}\s*=\s*\((?P<order>(?P=blue)\s*\|\s*(?P=alpha))\)\s*\|\s*(?P<last>(?P=red))\s*;'
)


def _packed_color_channels(source, name, header, rows):
    """Restore the register allocation of two unsigned channels in packed colors."""
    changes = [(i, left, right) for i, (mark, left, right) in enumerate(rows) if mark != ' ']
    if len(changes) != 9 or any(rows[i][0] != 'r' for i, _, _ in changes):
        return None
    indices, target, current = zip(*changes)
    if tuple(i - indices[0] for i in indices) != (0, 1, 2, 3, 4, 5, 7, 8, 9):
        return None
    target = normalized_integer_lines(target)
    current = normalized_integer_lines(current)
    expected = (
        'srl $v0, $a0, 1', 'sll $v0, $v0, 16', 'addiu $v1, $zero, 255',
        'subu $v1, $v1, $a0', 'ori $v1, $v1, 64', 'or $a0, $v0, $a1',
        'srl $v0, $v0, 1', 'or $a0, $a0, $v1', 'srl $v1, $v1, 1',
    )
    swap = {'$v0': '$v1', '$v1': '$v0'}
    swapped = tuple(re.sub(r'\$v[01]\b', lambda match: swap[match[0]], op) for op in expected)
    if tuple(target) != expected or tuple(current) != swapped:
        return None
    part = plain_repair_view(source, name, header)
    if not part:
        return None
    matches = list(_PACKED_CHANNELS.finditer(part.clean, part.opening + 1, part.end))
    if len(matches) != 1:
        return None
    hit = matches[0]
    red, blue, alpha, value = (hit[key] for key in ('red', 'blue', 'alpha', 'value'))
    prefix = part.clean[part.opening + 1:hit.start()]
    local_decls = re.findall(rf'\bu32\s+({IDENT}(?:\s*,\s*{IDENT})*)\s*(?:;|=)', prefix)
    locals_ = {local for decl in local_decls for local in re.findall(IDENT, decl)}
    if (len({red, blue, alpha, value}) != 4 or not {red, blue, alpha, value} <= locals_
            or re.search(r'/[*/]', source[hit.start():hit.end()])):
        return None
    start = hit.end('indent')
    end = part.clean.index(';', start, hit.end()) + 1
    return edit(source, [
        (start, end, f'do {{ {source[start:end]} }} while (0);'),
        (*hit.span('order'), f'{red} | {alpha}'),
        (*hit.span('last'), blue),
    ])


_SCALED_FIELD = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<dest>{IDENT}\s*->\s*{IDENT})\s*=\s*'
    rf'(?P<scale>\(\s*(?P<local>{IDENT})\s*\*\s*5[uU]?\s*\)\s*<<\s*5)\s*;'
)


def _scaled_field_store(source, name, header, rows):
    """Reuse an unsigned local before the scaled value feeds a delay-slot store."""
    matches = []
    for i in range(2, len(rows) - 2):
        window = rows[i - 2:i + 3]
        if tuple(row[0] for row in window) != (' ', ' ', 'r', ' ', 'r'):
            continue
        target = normalized_integer_lines(row[1] for row in window)
        current = normalized_integer_lines(row[2] for row in window)
        if tuple(target[:3]) != ('sll $v0, $a0, 2', 'addu $v0, $v0, $a0', 'sll $a0, $v0, 5'):
            continue
        store = re.fullmatch(rf'sw \$a0, ({NUMBER}\(\$s[0-7]\))', target[4])
        if (store and current[2] == 'sll $v0, $v0, 5' and current[4] == f'sw $v0, {store[1]}'
                and target[3].startswith(('beqz ', 'bnez '))):
            matches.append(i)
    if len(matches) != 1:
        return None
    part = view(source, name)
    if not part:
        return None
    hits = list(_SCALED_FIELD.finditer(part.clean, part.opening + 1, part.end))
    if len(hits) != 1:
        return None
    hit = hits[0]
    local = hit['local']
    unqualified = re.sub(rf'(?:->|\.)\s*{local}\b', '', part.body)
    tokens = '|'.join(set(re.findall(IDENT, hit['dest'])) | {local})
    if (re.search(rf'^\s*#\s*define\s+(?:{tokens})\b', header + '\n' + part.clean, re.M)
            or len(re.findall(rf'\b{local}\b', unqualified)) != 3
            or not any(decl['type'] == 'u32' and decl['name'] == local for decl in locals_for(part))
            or not re.search(rf'\b{local}\s*=\s*[^;]+;', part.clean[part.opening + 1:hit.start()])
            or re.search(r'/[*/]', source[hit.start():hit.end()])):
        return None
    indent = hit['indent']
    fixed = f'{indent}{{ {local} = {hit["scale"]}; {hit["dest"]} = {local}; }}'
    return edit(source, [(*hit.span(), fixed)])


_LINK_FIELDS = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<old>{IDENT}) = (?P<load>M2C_FIELD\((?P<anchor>{IDENT}), void \*\*, 0\));\s*'
    rf'if \((?P=old) != NULL\) \{{\s*M2C_FIELD\((?P=old), void \*\*, 4\) = (?P<node>{IDENT});\s*\}}\s*'
    rf'(?P<before>M2C_FIELD\((?P=node), void \*\*, 4\) = (?P=anchor);)\s*'
    rf'M2C_FIELD\((?P=node), void \*\*, 0\) = (?P<reload>\(void \*\) (?P=load));\s*'
    rf'M2C_FIELD\((?P=anchor), void \*\*, 0\) = (?P=node);'
)


def _link_pointer_reload(source, name, rows):
    """Move the next-pointer reload before the previous-pointer store as in the target."""
    changed = [(i, row) for i, row in enumerate(rows) if row[0] != ' ']
    if len(changed) != 2:
        return None
    (first, earlier), (last, later) = changed
    if first < 3 or last != first + 2 or earlier != ('o', '', 'sw $a1, 4($v1)'):
        return None
    if later != ('o', earlier[2], '') or rows[first + 1] != (' ', 'lw $v0, ($a1)', 'lw $v0, ($a1)'):
        return None
    if rows[first - 1] != (' ', 'sw $v1, 4($v0)', 'sw $v1, 4($v0)'):
        return None
    part = view(source, name)
    if not part:
        return None
    hits = list(_LINK_FIELDS.finditer(part.clean, part.opening + 1, part.end))
    if len(hits) != 1:
        return None
    hit = hits[0]
    old, anchor, node = (hit[key] for key in ('old', 'anchor', 'node'))
    if (len({old, anchor, node}) != 3 or len(re.findall(rf'\b{old}\b', part.body)) != 4
            or not re.search(rf'\bvoid\s*\*\s*{old}\s*;', part.body)
            or re.search(r'/[*/]', source[hit.start():hit.end()])):
        return None
    start = hit.start('before')
    return edit(source, [
        (start, start, f'{old} = {hit["load"]};\n{hit["indent"]}'),
        (*hit.span('reload'), old),
    ])


_RECORD_RESET = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<load>{IDENT} = M2C_FIELD\((?P<record>{IDENT}), s32 \*, 0\);)\s*'
    rf'(?P<zeroes>M2C_FIELD\((?P=record), s8 \*, 0x18\) = 0;\s*'
    rf'M2C_FIELD\((?P=record), u8 \*, 0x19\) = 0U;\s*'
    rf'M2C_FIELD\((?P=record), s8 \*, 0x1[Cc]\) = 0;\s*'
    rf'M2C_FIELD\((?P=record), s8 \*, 0x1[Dd]\) = 0;\s*'
    rf'M2C_FIELD\((?P=record), s16 \*, 0x14\) = 0;\s*'
    rf'M2C_FIELD\((?P=record), s32 \*, 0x10\) = 0;)\s*'
    rf'(?P<reset>M2C_FIELD\((?P=record), f32 \*, 0x[Cc]\) = 1\.0f;)'
)


def _stage_record_float_reset(source, name, rows):
    """Place a disjoint float reset before the saved pointer reload."""
    changed = [(i, row) for i, row in enumerate(rows) if row[0] != ' ']
    if len(changed) != 2:
        return None
    (first, earlier), (last, later) = changed
    load = 'lw $a0, ($s0)'
    if last != first + 3 or earlier != ('o', '', load) or later != ('o', load, ''):
        return None
    target = normalized_integer_lines(row[1] for row in rows[first + 1:last + 7])
    if target != (
        'lui $at, 16256', 'mtc1 $at, $f0', load, 'sb $zero, 24($s0)',
        'sb $zero, 25($s0)', 'sb $zero, 28($s0)', 'sb $zero, 29($s0)',
        'sh $zero, 20($s0)', 'sw $zero, 16($s0)',
    ):
        return None
    part = view(source, name)
    if not part:
        return None
    hits = list(_RECORD_RESET.finditer(part.clean, part.opening + 1, part.end))
    if len(hits) != 1:
        return None
    hit = hits[0]
    if re.search(r'/[*/]', source[hit.start():hit.end()]):
        return None
    indent = hit['indent']
    fixed = f'{indent}{hit["reset"]}\n{indent}{hit["load"]}\n{indent}{hit["zeroes"]}'
    return edit(source, [(*hit.span(), fixed)])


_VOLATILE_TABLE = re.compile(
    rf'\b(?P<dst>{IDENT})\s*=\s*\((?P<type>{IDENT})\s*\*\)'
    rf'\(\(u32\)\((?P<index>{IDENT})\s*\*\s*sizeof\((?P=type)\)\)\s*\+\s*\(u32\)(?P<base>{IDENT})\);'
)


def _volatile_table_base(source, name, header, rows):
    """Stage the volatile table read before scaling its index."""
    changed = [(i, row) for i, row in enumerate(rows) if row[0] != ' ']
    if len(changed) != 2:
        return None
    (first, earlier), (last, later) = changed
    shift = 'sll $v1, $v0, 1'
    if last != first + 3 or earlier != ('o', '', shift) or later != ('o', shift, ''):
        return None
    target = normalized_integer_lines(row[1] for row in rows[first + 1:last + 4])
    if len(target) != 6:
        return None
    hi = re.fullmatch(rf'lui \$a0, %hi\(({IDENT})\)', target[0])
    if not hi or target[1:] != (
        f'lw $a0, %lo({hi[1]})($a0)', shift, 'addu $v1, $v1, $v0',
        'sll $v1, $v1, 2', 'addu $v1, $v1, $a0',
    ):
        return None
    part = view(source, name)
    if not part:
        return None
    hits = list(_VOLATILE_TABLE.finditer(part.clean, part.opening + 1, part.end))
    if len(hits) != 1:
        return None
    hit = hits[0]
    dst, record, index, base = (hit[key] for key in ('dst', 'type', 'index', 'base'))
    staged_base, offset = '__repair_table_base', '__repair_table_offset'
    context = header + '\n' + part.clean[:part.opening]
    if (base != hi[1] or not re.search(rf'\bextern\s+{record}\s*\*\s*volatile\s+{base}\s*;', context)
            or not re.search(rf'\bu32\s+{index}\b', part.body[:hit.start() - part.opening - 1])
            or any(local in source or local in header for local in (staged_base, offset))
            or re.search(r'/[*/]', source[hit.start():hit.end()])):
        return None
    fixed = (f'{{ {record} *{staged_base} = {base}; '
             f'u32 {offset} = {index} * sizeof({record}); '
             f'{dst} = ({record} *)({offset} + (u32){staged_base}); }}')
    return edit(source, [(*hit.span(), fixed)])


_NONNULL_RESULT = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<result>{IDENT})\s*=\s*(?P<callee>{IDENT})'
    rf'\((?P<record>{IDENT}),\s*{IDENT}\);\s*'
    rf'M2C_FIELD\((?P=record), void \*\*, (?P<slot>{NUMBER})\)\s*=\s*(?P=result);\s*'
    rf'if\s*\((?P=result)\s*!=\s*NULL\)\s*\{{'
)


def _nonnull_call_result(source, name, header, rows):
    """Keep the result in the return register until its non-null branch."""
    changes = [(i, row) for i, row in enumerate(rows) if row[0] != ' ']
    if len(changes) != 4:
        return None
    first = changes[0][0]
    if [i for i, _ in changes] != list(range(first, first + 4)) or first < 2:
        return None
    move, branch, store, delayed = (row for _, row in changes)
    if move != ('o', '', 'move $a1, $v0') or delayed != ('o', move[2], ''):
        return None
    guard = re.fullmatch(rf'beqz \$v0, ({NUMBER})', branch[1])
    field = re.fullmatch(rf'sw \$v0, ({NUMBER})\(\$s\d+\)', store[1])
    if not guard or not field or branch != ('r', branch[1], f'beqz $a1, {guard[1]}'):
        return None
    if store != ('r', store[1], store[1].replace('$v0', '$a1')):
        return None
    call = re.fullmatch(rf'jal ({IDENT})', rows[first - 2][1])
    part = view(source, name)
    local = '__repair_nonnull_result'
    if not part or not call or local in source or local in header:
        return None
    hits = [hit for hit in _NONNULL_RESULT.finditer(part.clean, part.opening + 1, part.end)
            if hit['callee'] == call[1] and integer(hit['slot']) == integer(field[1])]
    if len(hits) != 1:
        return None
    hit = hits[0]
    end = close(part.clean, hit.end() - 1, '{', '}')
    if not end:
        return None
    result = hit['result']
    body = source[hit.end():end - 1]
    pointer_field = re.compile(rf'(\bM2C_FIELD\(\s*){result}\b')
    if (len(pointer_field.findall(body)) != 3 or len(re.findall(rf'\b{result}\b', body)) != 3
            or re.search(r'/[*/]|\b(?:goto|case|default)\b', source[hit.start():end])):
        return None
    fixed = f'\n{hit["indent"]}    void *{local} = {result};' + pointer_field.sub(rf'\g<1>{local}', body)
    return edit(source, [(hit.end(), end - 1, fixed)])


_INITIAL_RECORD = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<pointer>{IDENT})\s*=\s*'
    rf'M2C_FIELD\({IDENT}, void \*\*, (?P<slot>{NUMBER})\);\s*'
    rf'{IDENT}\s*=\s*1;\s*if\s*\((?P=pointer)\s*!=\s*NULL\)\s*\{{\s*'
    rf'{IDENT}\s*=\s*\*\(u32 \*\)\(\(s8 \*\)(?P=pointer)\s*\+\s*(?P<word>{NUMBER})\);\s*'
    rf'if\s*\(M2C_FIELD\((?P=pointer), u8 \*, (?P<byte>{NUMBER})\)\s*!=\s*{NUMBER}\)'
)


def _initial_record_pointer(source, name, header, rows):
    """Split the guarded initial record read from subsequent pointer reloads."""
    if len(rows) < 7 or tuple(row[0] for row in rows[:7]) != (' ', 'r', ' ', 'r', ' ', 'r', 'r'):
        return None
    target = normalized_integer_lines(row[1] for row in rows[:7])
    current = normalized_integer_lines(row[2] for row in rows[:7])
    load = re.fullmatch(rf'lw \$v0, ({NUMBER})\(\$a3\)', target[1])
    byte = re.fullmatch(rf'lbu \$v1, ({NUMBER})\(\$v0\)', target[5])
    word = re.fullmatch(rf'lw \$a0, ({NUMBER})\(\$v0\)', target[6])
    if not load or not byte or not word or not target[3].startswith('beqz $v0, '):
        return None
    expected = list(target)
    for i in (1, 3, 5, 6):
        expected[i] = target[i].replace('$v0', '$a1')
    if tuple(expected) != current:
        return None
    part = view(source, name)
    local = '__repair_initial_record'
    if not part or local in source or local in header:
        return None
    hits = list(_INITIAL_RECORD.finditer(part.clean, part.opening + 1, part.end))
    if len(hits) != 1:
        return None
    hit = hits[0]
    if any(integer(hit[key]) != integer(match[1]) for key, match in
           (('slot', load), ('byte', byte), ('word', word))):
        return None
    pointer = hit['pointer']
    prefix = part.clean[part.opening + 1:hit.start()]
    tail = part.clean[hit.end():part.end]
    references = re.compile(rf'\b{pointer}\b')
    if (len(references.findall(prefix)) != 1 or not re.search(rf'(?m)^[ \t]*void\s*\*\s*{pointer}\s*;', prefix)
            or re.search(r'\bgoto\b', part.body)
            or re.search(r'/[*/]', source[hit.start():hit.end()])):
        return None
    # Every later use must be in the store immediately following its own reload,
    # possibly separated by scalar assignments. No read can cross a block edge.
    reload_and_store = re.compile(
        rf'(?m)^[ \t]*{pointer} = M2C_FIELD\({IDENT}, void \*\*, {NUMBER}\);\s*'
        rf'(?:{IDENT} = [^;{{}}]+;\s*)*M2C_FIELD\({pointer}, u32 \*, {NUMBER}\) = [^;{{}}]+;'
    )
    for reload in reversed(list(reload_and_store.finditer(tail))):
        if tail[:reload.start()].rstrip()[-1:] not in ('{', '}', ';'):
            return None
        statement = reload[0].partition(';')[2]
        field_reads = re.findall(rf'\bM2C_FIELD\(\s*{pointer}\s*,', statement)
        if len(field_reads) != len(references.findall(statement)):
            return None
        if re.search(r'\b(?:case|default|if|else|switch|while|for)\b|:', statement):
            return None
        tail = tail[:reload.start()] + tail[reload.end():]
    if references.search(tail):
        return None
    fixed = re.sub(rf'\b{pointer}\b', local, source[hit.start():hit.end()])
    return edit(source, [(*hit.span(), f'{hit["indent"]}void *{local};\n{fixed}')])


_SHADE_CLAMP = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)if \((?P<shade>{IDENT}) != 0xFF\) \{{(?P<clamp>\s*'
    rf'if \((?P<sum>{IDENT}) >= 0\) \{{\s*(?P=shade) \+= 0x10;\s*'
    rf'if \((?P=sum) >= 0x100\) \{{\s*(?P=shade) = 0xFF;\s*\}}\s*'
    rf'\}} else \{{\s*(?P=shade) = 0;\s*\}})\s*'
    rf'{IDENT} = M2C_FIELD\({IDENT}, void \*\*, 0x10\);\s*'
    rf'(?P=shade) = (?P<mask>(?P=shade) & 0xFF);'
)


def _shade_clamp_storage(source, name, header, rows):
    """Keep the byte and its signed clamp in separate locals until packing."""
    target = normalized_integer_lines(left for _, left, _ in rows if left)
    current = normalized_integer_lines(right for _, _, right in rows if right)
    if len(target) != len(current):
        return None
    witnesses = [
        i for i, op in enumerate(target[:-13])
        if op == 'lbu $v1, 16($v0)' and current[i] == 'lbu $a0, 16($v0)'
        and target[i + 3] == 'addiu $v0, $v1, 16' and current[i + 3] == 'addiu $a2, $a0, 16'
        and target[i + 4].startswith('bltz $v0, ')
        and current[i + 4] == target[i + 4].replace('$v0', '$a2')
        and target[i + 5] == 'slti $v0, $v0, 256' and current[i + 5] == 'slti $v0, $a2, 256'
        and target[i + 12] == 'andi $v1, $v1, 255' and current[i + 12] == 'andi $a0, $a0, 255'
    ]
    if len(witnesses) != 1:
        return None
    part = view(source, name)
    local = '__repair_clamped_shade'
    if not part or local in source or local in header:
        return None
    hits = list(_SHADE_CLAMP.finditer(part.clean, part.opening + 1, part.end))
    if len(hits) != 1:
        return None
    hit = hits[0]
    shade = hit['shade']
    prefix = part.clean[part.opening + 1:hit.start()]
    if (not re.search(rf'(?m)^[ \t]*s32 {shade};', prefix)
            or re.search(rf'&\s*\(*\s*{shade}\b', part.body)
            or re.search(r'/[*/]', source[hit.start():hit.end()])):
        return None
    start, end = hit.span('clamp')
    clamp = re.sub(rf'\b{shade}\b', local, source[start:end])
    declaration = f'\n{hit["indent"]}    s32 {local} = {shade};'
    return edit(source, [(start, end, declaration + clamp), (*hit.span('mask'), f'{local} & 0xff')])


def variants(source, name, header, rows):
    if choices := _collapse_identical_assignments(source, name, header, rows):
        return choices
    if candidate := _inline_interpolated_product(source, name, rows):
        return [('measured_inline_interpolated_product', candidate)]
    if candidate := _byte_subtraction_carrier(source, name, rows):
        return [('measured_byte_subtraction_carrier', candidate)]
    if candidate := _float_scale_carrier(source, name, rows):
        return [('measured_float_scale_carrier', candidate)]
    if candidate := _early_float_load(source, name, header, rows):
        return [('measured_early_float_field_load', candidate)]
    if candidate := _guarded_constant_stores(source, name, rows):
        return [('guarded_constant_stores', candidate)]
    if candidate := _byte_guard_return(source, name, header, rows):
        return [('measured_byte_guard_return', candidate)]
    if candidate := _in_place_float_ranges(source, name, header, rows):
        return [('measured_in_place_float_ranges', candidate)]
    if candidate := _float_sum_destination(source, name, header, rows):
        return [('measured_float_sum_destination', candidate)]
    if candidate := _packed_color_channels(source, name, header, rows):
        return [('measured_packed_color_channels', candidate)]
    if candidate := _scaled_field_store(source, name, header, rows):
        return [('measured_scaled_field_store', candidate)]
    if candidate := _link_pointer_reload(source, name, rows):
        return [('measured_link_pointer_reload', candidate)]
    if candidate := _stage_record_float_reset(source, name, rows):
        return [('measured_record_float_reset', candidate)]
    if candidate := _volatile_table_base(source, name, header, rows):
        return [('measured_volatile_table_base', candidate)]
    if candidate := _nonnull_call_result(source, name, header, rows):
        return [('measured_nonnull_call_result', candidate)]
    if candidate := _initial_record_pointer(source, name, header, rows):
        return [('measured_initial_record_pointer', candidate)]
    if candidate := _shade_clamp_storage(source, name, header, rows):
        return [('measured_shade_clamp_storage', candidate)]
    if not 23 <= len(rows) <= 125:
        return []
    changes = [(i, left, right) for i, (mark, left, right) in enumerate(rows) if mark != ' ']
    if len(changes) not in (3, 4, 6):
        return []
    moved = _moved_pair(rows, changes)
    if moved and _RELOC_STORE.fullmatch('\n'.join(moved)):
        result = [fixed for family, fixed in goto_structure_repairs.variants(source, name)
                  if family == 'goto_forward_else']
        return [('measured_split_store_tail', result[0])] if len(result) == 1 else []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    if len(changes) == 3 and (call := _STAGED_CALL.search(target)) and _call_rotation(rows, changes, call):
        family, witness, build = 'measured_staged_call_result', call, _staged_call
    elif len(changes) == 4 and (indirect := _INDIRECT_CALL.search(target)) and _indirect_rotation(rows, changes, indirect):
        family, witness, build = 'measured_post_indirect_call_update', indirect, _after_indirect_call
    elif moved and (limit := _MOVE_LIMIT.search(target)):
        expected = (f'addiu $a2, $zero, {limit["literal"]}', f'sh $a2, {limit["dst"]}($a0)')
        if moved != expected:
            return []
        family, witness, build = 'measured_late_halfword_limit', limit, _late_limit
    elif len(changes) == 6 and (conversion := _FLOAT.fullmatch(target)):
        if not any(left == 'cvt.s.d $f12, $f0' and right == 'cvt.s.d $f0, $f0' for _, left, right in changes):
            return []
        family, witness, build = 'measured_staged_float_conversion', conversion, _staged_conversion
    else:
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    fixed = build(part, name, header, witness)
    return [(family, fixed)] if fixed else []


def _moved_pair(rows, changes):
    if len(changes) != 4:
        return None
    (a, _, old0), (b, _, old1), (c, want0, right0), (d, want1, right1) = changes
    if (b != a + 1 or c <= b or d != c + 1 or right0 or right1 or changes[0][1] or changes[1][1]
            or (want0, want1) != (old0, old1)):
        return None
    moved = normalized_integer_lines((want0, want1))
    if _RELOC_STORE.fullmatch('\n'.join(moved)):
        # The target delays the first slot's store until after the next
        # call's argument setup, while the draft joins the branches.
        setup = [row[1] for row in rows[b + 1:c]]
        if (a < 2 or d + 1 >= len(rows) or len(setup) != 2 or setup[0] != 'move $a0, $s0'
                or not re.fullmatch(r'addiu \$a1, \$zero, \d+', setup[1])
                or not rows[a - 2][1].startswith('jal ') or rows[a - 2][1] != rows[d + 1][1]):
            return None
    return moved


def _late_limit(part, name, _header, target):
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(void \*({IDENT}), void \*({IDENT})\)\s*$', part.clean[:part.opening])
    stores = _LIMIT_SOURCE.match(part.body)
    if not signature or not stores or signature.groups() != (stores['dst'], stores['src']):
        return None
    fields = ('src0', 'src1')
    if ([integer(stores[key]) for key in fields] != [int(target[key]) for key in fields]
            or integer(stores['field']) != int(target['dst']) or integer(stores['value']) != int(target['literal'])):
        return None
    start = part.opening + 1
    coordinates = part.source[start + stores.start('coordinates'):start + stores.end('coordinates')]
    literal = part.source[start + stores.start('literal'):start + stores.end('literal')]
    return edit(part.source, [(start, start + stores.end(), coordinates + literal)])


def _staged_conversion(part, name, header, target):
    source = _FLOAT_SOURCE.fullmatch(part.body)
    signature = re.search(rf'\bs32\s+{re.escape(name)}\(s32 ({IDENT})\)\s*$', part.clean[:part.opening])
    local = '__repair_float_stage'
    if not source or not signature or signature[1] != source['arg'] or local in part.source or local in header:
        return None
    if any(source[key] != target[key] for key in ('first', 'second', 'call')) or source['call'] == name:
        return None
    bits = int.from_bytes(struct.pack('>f', float(source['scale'][:-1])), 'big')
    if bits != int(target['scale']) << 16:
        return None
    fixed = f'''
    f32 {local};

    {local} = (f32)((f64){source['arg']} * {source['first']});
    {local} = (f32)((f64){local} * {source['second']});
    {local} = {source['call']}({local});
    {local} *= {source['scale']};
    return (s32){local};
'''
    return edit(part.source, [(part.opening + 1, part.end - 1, fixed)])

def _call_rotation(rows, changes, target):
    (a, *first), (b, *middle), (c, *last) = changes
    return (b == a + 2 and c == b + 2 and first == ['', 'lw $s0, ($v0)']
            and middle == ['lw $s0, ($v0)', 'move $a1, $zero'] and last == ['move $a1, $zero', '']
            and rows[b + 1][1] == f'jal {target["call"]}')


def _indirect_rotation(rows, changes, target):
    sub, load = 'subu $s3, $s3, $s1', f'lw $v0, {target["slot"]}($s0)'
    (a, *first), (b, *second), (c, *third), (d, *fourth) = changes
    first, second, third, fourth = (normalized_integer_lines(pair) for pair in (first, second, third, fourth))
    return (b == a + 2 and c == b + 2 and d == c + 1 and d + 1 < len(rows)
            and (first, second, third, fourth) == (('', sub), ('', load), (load, ''), (sub, ''))
            and rows[d + 1][1] == 'jalr $v0')


def _staged_call(part, _name, header, target):
    local = '__repair_call_result'
    matches = list(_CALL_SOURCE.finditer(part.body))
    if len(matches) != 1 or local in part.source or local in header:
        return None
    match = matches[0]
    if (match['call'] != target['call'] or len({match[key] for key in ('addr', 'base', 'input', 'call')}) != 4
            or any(integer(match[key]) != int(target[key]) for key in ('field', 'arg', 'out'))):
        return None
    start = part.opening + 1
    address_start = start + match.start('address')
    whitespace = re.match(r'\s*', match['address'])[0]
    call = part.source[start + match.start('call'):start + match.end()]
    return edit(part.source, [
        (start, start, f'\n    s32 {local};'),
        (address_start, address_start, f'{whitespace}{local} = {call}'),
        (start + match.start('call'), start + match.end(), f'{local};'),
    ])


def _after_indirect_call(part, _name, _header, target):
    matches = list(_INDIRECT_SOURCE.finditer(part.body))
    if len(matches) != 1:
        return None
    match = matches[0]
    left, right = match['left'], match['right']
    if (integer(match['slot']) != int(target['slot']) or integer(match['mode']) != int(target['mode'])
            or left == right or any(
                not re.search(rf'\bs32\s+{local}\s*;', part.body[:match.start()])
                or re.search(rf'&\s*{local}\b', part.body) for local in (left, right)
            )):
        return None
    start = part.opening + 1
    call = part.source[start + match.start('call'):start + match.end('call')]
    update = part.source[start + match.start('update'):start + match.end('update')]
    return edit(part.source, [(start + match.start(), start + match.end(), call + match['gap'] + update)])
