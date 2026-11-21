"""Recover source boundaries behind three small KMC scheduling differences."""

import re
import struct

from . import goto_structure_repairs
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
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
