"""Measured MIPS repairs for byte arithmetic, a masked cursor and a recursive accumulator."""

import re

from . import mips_return_paths
from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .pattern_repairs import close

REG = r'\$[a-z][a-z0-9]*'
SAVED = r'\$s[0-7]'
BYTE_BIAS = re.compile(
    rf'lbu \$v1, (?P<index>{NUMBER})\(\$a0\)\n'
    rf'lw \$v0, (?P<table>{NUMBER})\(\$a1\)\nlw \$a0, (?P<direct>{NUMBER})\(\$a0\)\n'
    rf'sll \$v1, \$v1, (?P<shift>{NUMBER})\naddu \$v1, \$v1, \$v0\n'
    rf'lbu \$v0, (?P<left>{NUMBER})\(\$a0\)\nlbu \$v1, (?P<right>{NUMBER})\(\$v1\)\n'
    rf'addiu \$v0, \$v0, -(?P<bias>{NUMBER})\naddu \$v1, \$v1, \$v0'
)


def _byte_bias(part, rows):
    if len(rows) < 9 or len(rows) > 24:
        return None
    target = BYTE_BIAS.fullmatch('\n'.join(row[1] for row in rows[:9]))
    if not target or not 1 <= integer(target['shift']) <= 8 or not 1 <= integer(target['bias']) <= 255:
        return None
    swap = {'$v0': '$v1', '$v1': '$v0'}
    def swapped(text):
        return re.sub(r'\$v[01]\b', lambda m: swap[m[0]], text)
    expected = [swapped(rows[i][1]) for i in (0, 1)] + [rows[2][1]]
    expected += [swapped(rows[i][1]) for i in (3, 4)]
    expected += [rows[6][1].replace('($v1)', '($v0)'), rows[5][1], swapped(rows[7][1]), rows[8][1]]
    if [row[2] for row in rows[:9]] != expected or any(row[0] != ' ' for row in rows[9:]):
        return None

    expression = re.search(
        rf'(?m)^[ \t]*{IDENT}\s*=\s*(?P<rhs>'
        rf'(?P<indexed>M2C_FIELD\(\(\(M2C_FIELD\((?P<a>{IDENT}), u8 \*, (?P<index>{NUMBER})\) '
        rf'\* (?P<scale>{NUMBER})\) \+ M2C_FIELD\((?P<b>{IDENT}), s32 \*, (?P<table>{NUMBER})\)\), '
        rf'u8 \*, (?P<right>{NUMBER})\)) \+ \('
        rf'(?P<direct_byte>M2C_FIELD\(M2C_FIELD\((?P=a), void \*\*, (?P<direct>{NUMBER})\), '
        rf'u8 \*, (?P<left>{NUMBER})\)) - (?P<bias>{NUMBER})\));',
        part.body)
    if (not expression or expression['a'] == expression['b']
            or integer(expression['scale']) != 1 << integer(target['shift'])
            or any(integer(target[key]) != integer(expression[key])
                   for key in ('index', 'table', 'right', 'direct', 'left', 'bias'))):
        return None
    a, b = expression['a'], expression['b']
    if not re.search(rf'\(void\s*\*\s*{a},\s*void\s*\*\s*{b}\)\s*$', part.clean[:part.opening]):
        return None
    start = part.opening + 1
    indexed = expression['indexed'].replace(f"* {expression['scale']}", f"<< {integer(target['shift'])}", 1)
    return edit(part.source, [(start + expression.start('rhs'), start + expression.end('rhs'),
                               f"({indexed} - {expression['bias']}) + {expression['direct_byte']}")])


_LOOP = re.compile(
    rf'beqz (?P<node>{REG}), \S+\n(?:move (?P<counter>{REG}), \$zero|addu (?P<zeroed>{REG}), \$zero, \$zero)\n'
    rf'andi \$a0, \$a0, (?P<mask>{NUMBER})\nandi (?P<temp>{REG}), (?P<index>{REG}), (?P=mask)\n'
    r'bne (?P=temp), \$a0, \S+\nnop\n'
    rf'lw (?P=temp), (?P<field>{NUMBER})\((?P=node)\)\nori (?P=temp), (?P=temp), (?P<flag>{NUMBER})\n'
    r'j \S+\nsw (?P=temp), (?P=field)\((?P=node)\)\n'
    rf'lw (?P=node), (?P<next>{NUMBER})\((?P=node)\)\nbnez (?P=node), \S+\n'
    r'addiu (?P=index), (?P=index), (?:0x1|1)'
)


def _loop_mask(part, header, rows, asm):
    local = '__repair_masked_index'
    if local in part.source + header or not (graph := mips_return_paths.graph(asm)):
        return None
    instructions, edges = graph
    # The back edge enters the counter mask, skipping the incoming argument's mask.
    for branch, entry in edges.items():
        if branch - entry != 8 or entry < 3:
            continue
        start = entry - 3
        match = _LOOP.fullmatch('\n'.join(' '.join(op.split()) for op in instructions[start:branch + 2]))
        if (match and match['index'] == (match['counter'] or match['zeroed'])
                and edges.get(entry + 1) == branch - 1 and edges.get(start) == edges.get(entry + 5) == branch + 2):
            break
    else:
        return None
    if not any(marker != ' ' and 'andi ' in target and '$a0, $a0,' in target and '$a0, $a0,' not in candidate
               for marker, target, candidate in rows):
        return None
    signature = re.search(rf'\bvoid\s+{IDENT}\(s32\s+(?P<formal>{IDENT})\)\s*$', part.clean[:part.opening])
    if not signature:
        return None
    formal = signature['formal']
    source_loop = re.search(
        rf'(?m)^(?P<indent>[ \t]*)if \((?P<node>{IDENT}) != NULL\) {{\s*(?P<label>{IDENT}):\s*'
        rf'if \(\((?P<counter>{IDENT}) & (?P<mask>{NUMBER})\) == (?P<arg>\({formal} & (?P=mask)\))\) {{\s*'
        rf'(?P<field>M2C_FIELD\((?P=node), s32 \*, (?P<field_at>{NUMBER})\)) = \(s32\) \('
        rf'(?P=field) \| (?P<flag>{NUMBER})\);\s*return;\s*}}\s*'
        rf'(?P=node) = M2C_FIELD\((?P=node), void \*\*, (?P<next>{NUMBER})\);\s*(?P=counter) \+= 1;\s*'
        rf'(?P<tail>if \((?P=node) == NULL\) {{\s*}} else {{(?P<back>\s*goto (?P=label);\s*)}})',
        part.body)
    if (not source_loop or any(integer(match[asm_key]) != integer(source_loop[c_key])
                               for asm_key, c_key in (('mask', 'mask'), ('field', 'field_at'),
                                                      ('flag', 'flag'), ('next', 'next')))):
        return None
    start = part.opening + 1
    indent = source_loop['indent']
    incoming = source_loop['arg'][1:-1]
    return edit(part.source, [
        (start, start, f'\n    s32 {local};'),
        (start + source_loop.start('label'), start + source_loop.start('label'), f'{indent}    {local} = {incoming};\n'),
        (start + source_loop.start('arg'), start + source_loop.end('arg'), local),
        (start + source_loop.start('tail'), start + source_loop.end('tail'),
         f"if ({source_loop['node']} != NULL) {{{source_loop['back']}}}"),
    ])


_RECURSION = re.compile(
    rf'addiu \$sp, \$sp, -{NUMBER}\nsw {SAVED}, {NUMBER}\(\$sp\)\n'
    rf'move (?P<context>{SAVED}), \$a0\n(?:sw {REG}, {NUMBER}\(\$sp\)\n){{2}}'
    rf'jal (?P<getter>{IDENT})\nsw {SAVED}, {NUMBER}\(\$sp\)\n'
    rf'move (?P<count>{SAVED}), \$v0\nbeqz (?P=count), (?P<exit>\S+)\nmove \$v0, (?P=count)\n'
    rf'move \$a0, (?P=context)\njal (?P<allocate>{IDENT})\nmove \$a1, (?P=count)\n'
    rf'move (?P<block>{SAVED}), \$v0\nbeqz (?P=block), (?P=exit)\nmove \$v0, (?P=count)\n'
    rf'jal (?P<self>{IDENT})\nmove \$a0, (?P=context)\naddu (?P=count), (?P=count), \$v0\n'
    rf'jal (?P<release>{IDENT})\nmove \$a0, (?P=block)\nmove \$v0, (?P=count)'
)


def _recursive_accumulator(part, name, header, rows):
    target = [row[1] for row in rows if row[1]]
    if len(target) not in range(23, 33):
        return None
    match = _RECURSION.fullmatch('\n'.join(target[:22]))
    if not match or match['self'] != name or len({match[key] for key in ('context', 'count', 'block')}) != 3:
        return None
    getter, allocate, release = (match[key] for key in ('getter', 'allocate', 'release'))
    if (len({name, getter, allocate, release}) != 4 or not any(row[0] != ' ' for row in rows)
            or re.search(rf'\b{getter}\s*\(', _blank(header))
            or not re.search(rf'(?m)^[ \t]*s32 {getter}\(\);[ \t]*/\* extern \*/', part.source[:part.opening])):
        return None
    signature = re.search(rf'\bs32\s+{name}\(s32\s+(?P<formal>{IDENT})\)\s*$', part.clean[:part.opening])
    if not signature:
        return None
    formal = signature['formal']
    if not (closing := close(part.clean, part.opening, '{', '}')):
        return None
    body = re.fullmatch(
        rf'\s*s32 (?P<sum>{IDENT});\s*s32 (?P<count>{IDENT});\s*s32 (?P<block>{IDENT});\s*s32 (?P<out>{IDENT});\s*'
        rf'(?P=count) = {getter}\(\);\s*(?P=out) = (?P=count);\s*if \((?P=count) != 0\) {{\s*'
        rf'(?P=block) = {allocate}\({formal}, (?P=count)\);\s*(?P=out) = (?P=count);\s*'
        rf'if \((?P=block) != 0\) {{\s*(?P=sum) = (?P=count) \+ {name}\({formal}\);\s*'
        rf'(?:(?P=out) = (?P=sum);\s*{release}\((?P=block)\);|'
        rf'{release}\((?P=block)\);\s*(?P=out) = (?P=sum);)\s*}}\s*}}\s*return (?P=out);\s*',
        part.clean[part.opening + 1:closing - 1])
    if not body or len({formal, *(body[key] for key in ('sum', 'count', 'block', 'out'))}) != 5:
        return None
    count, block = body['count'], body['block']
    replacement = (f'\n    s32 {count};\n    s32 {block};\n\n'
                   f'    {count} = {getter}({formal});\n    if ({count} != 0) {{\n'
                   f'        {block} = {allocate}({formal}, {count});\n        if ({block} != 0) {{\n'
                   f'            {count} += {name}({formal});\n            {release}({block});\n        }}\n'
                   f'    }}\n    return {count};\n')
    return edit(part.source, [(part.opening + 1, closing - 1, replacement)])


def variants(source, name, header, rows, asm):
    if not 9 <= len(rows) <= 40 or not (part := view(source, name)):
        return []
    if candidate := _byte_bias(part, rows):
        return [('indexed_byte_bias', candidate)]
    if 'goto' in part.body and (candidate := _loop_mask(part, header, rows, asm)):
        return [('masked_list_index', candidate)]
    if candidate := _recursive_accumulator(part, name, header, rows):
        return [('recursive_call_accumulator', candidate)]
    return []
