"""Measured KMC record scans and repeated layout stores."""

import re

from . import mips_return_paths, passthrough_argument_repairs
from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, calls, edit, integer, view
from .pattern_repairs import close

_RECORD_SCAN = re.compile(
    rf'andi \$a1, \$a1, (?P<mask>{NUMBER})\nsll \$v0, \$a1, (?P<shift1>{NUMBER})\n'
    rf'lw \$v1, (?P<table>{NUMBER})\(\$a0\)\naddu \$v0, \$v0, \$a1\nsll \$v0, \$v0, (?P<shift2>{NUMBER})\n'
    rf'addu \$t1, \$v1, \$v0\nlbu \$v0, (?P<count>{NUMBER})\(\$t1\)\nlw \$a1, (?P<records>{NUMBER})\(\$t1\)\n'
    r'beqz \$v0, \S+\n(?:move \$t0, \$zero|addu \$t0, \$zero, \$zero)\n'
    rf'addiu \$a0, \$a1, (?P<value>{NUMBER})\nlw \$v0, (?:0x0|0)?\(\$a1\)\nbnel \$v0, \$a2, \S+\n'
    rf'addiu \$t0, \$t0, (?P<one>{NUMBER})\nlb \$v0, -(?P<flag>{NUMBER})\(\$a0\)\nbnel \$v0, \$zero, \S+\n'
    r'addiu \$t0, \$t0, (?P=one)\nj \S+\nsw \$a3, (?:0x0|0)?\(\$a0\)\n'
    rf'addiu \$a0, \$a0, (?P<step>{NUMBER})\nlbu \$v1, (?P=count)\(\$t1\)\n'
    r'andi \$v0, \$t0, (?P=mask)\nsltu \$v0, \$v0, \$v1\nbnez \$v0, \S+\n'
    r'addiu \$a1, \$a1, (?P=step)\njr \$ra\nnop'
)


def _record_scan(part, name, header, asm):
    if '__repair_scan_' in part.source + header or not (graph := mips_return_paths.graph(asm)):
        return None
    instructions, edges = graph
    if edges != {8: 25, 12: 19, 15: 19, 17: 25, 23: 11}:
        return None
    target = _RECORD_SCAN.fullmatch('\n'.join(' '.join(row.split()) for row in instructions))
    if not target or integer(target['one']) != 1 or not all(0 <= integer(target[k]) <= 8 for k in ('shift1', 'shift2')):
        return None
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(void \*({IDENT}), s32 ({IDENT}), s32 ({IDENT}), s32 ({IDENT})\)\s*$',
                          part.clean[:part.opening])
    if not signature or not (end := close(part.clean, part.opening, '{', '}')):
        return None
    obj, entry_index, key, value = signature.groups()
    source = re.fullmatch(
        rf'\s*(?P<type>s32|char) \*(?P<record>{IDENT});\s*s32 (?P<i>{IDENT});\s*'
        rf'void \*(?P<entry>{IDENT});\s*void \*(?P<cell>{IDENT});\s*'
        rf'(?P<lookup>(?P=entry) = M2C_FIELD\({obj}, s32 \*, (?P<table>{NUMBER})\) \+ '
        rf'\(\({entry_index} & (?P<mask>{NUMBER})\) \* (?P<stride>{NUMBER})\);)\s*'
        rf'(?P<records_line>(?P=record) = M2C_FIELD\((?P=entry), s32 \*\*, (?P<records>{NUMBER})\);)\s*'
        rf'(?P=i) = 0;\s*if \((?P<limit>M2C_FIELD\((?P=entry), u8 \*, (?P<count>{NUMBER})\)) != 0\) {{\s*'
        rf'(?P=cell) = (?P=record) \+ (?P<value>{NUMBER});\s*(?P<loop>{IDENT}):\s*'
        rf'if \(\*(?P=record) != {key}\) {{\s*(?P=i) \+= 1;\s*goto (?P<advance>{IDENT});\s*}}\s*'
        rf'if \((?P<flag_expr>M2C_FIELD\((?P=cell), s8 \*, -(?P<flag>{NUMBER})\)) != 0\) {{\s*'
        rf'(?P=i) \+= 1;\s*(?P=advance):\s*(?P=cell) \+= (?P<step>{NUMBER});\s*(?P=record) \+= (?P=step);\s*'
        rf'if \(\(u32\) \((?P=i) & (?P=mask)\) >= \(u8\) (?P=limit)\) {{\s*}} else {{\s*goto (?P=loop);\s*}}\s*'
        rf'}} else {{\s*(?P<store>M2C_FIELD\((?P=cell), s32 \*, (?:0x0|0)\) = {value};)\s*}}\s*}}\s*',
        part.clean[part.opening + 1:end - 1])
    stride = ((1 << integer(target['shift1'])) + 1) << integer(target['shift2'])
    if (not source or len({source[k] for k in ('record', 'i', 'entry', 'cell')} | set(signature.groups())) != 8
            or source['loop'] == source['advance'] or integer(source['stride']) != stride or any(integer(source[k]) != integer(target[k])
            for k in ('table', 'mask', 'records', 'count', 'value', 'flag', 'step'))):
        return None
    record, i, entry, cell, limit, step, mask = (source[k] for k in ('record', 'i', 'entry', 'cell', 'limit', 'step', 'mask'))
    replacement = f'''
    s32 __repair_scan_key;
    char *{record};
    s32 {i};
    void *{entry};
    void *{cell};

    {source["lookup"]}
    __repair_scan_key = {key};
    {source["records_line"]}
    {i} = 0;
    if ({limit} == 0) goto __repair_scan_done;
    {cell} = {record} + {source["value"]};
__repair_scan_loop:
    if (*(s32 *){record} == __repair_scan_key) goto __repair_scan_flag;
    {i} += 1;
    goto __repair_scan_advance;
__repair_scan_flag:
    if ({source["flag_expr"]} == 0) goto __repair_scan_store;
    {i} += 1;
    goto __repair_scan_advance;
__repair_scan_store:
    {source["store"]}
    return;
__repair_scan_advance:
    {cell} += {step};
    {record} += {step};
    if ((u32)({i} & {mask}) < (u8){limit}) goto __repair_scan_loop;
__repair_scan_done:
    return;
'''
    return edit(part.source, [(part.opening + 1, end - 1, replacement)])


def _stage_layout(part, name, header, rows, asm):
    if '__repair_layout_' in part.source + header:
        return None
    changes = [i for i, row in enumerate(rows) if row[0] != ' ']
    if len(changes) not in (2, 3):
        return None
    read, moved = changes[:2]
    if moved != read + 3 or not 2 <= read < len(rows) - 6 or rows[read][2] or rows[moved][1]:
        return None
    field = re.fullmatch(rf'lw \$v0, (?P<in>{NUMBER})\(\$v1\)', rows[read][1])
    offset = re.fullmatch(rf'lw \$v1, (?P<base>{NUMBER})\(\$a0\)', rows[read - 1][1])
    reset = re.fullmatch(rf'sw \$zero, %lo\((?P<symbol>{IDENT})\)\(\$at\)', rows[read + 2][1])
    add = re.fullmatch(rf'addiu \$v0, \$v0, (?P<add>{NUMBER})', rows[moved + 1][1])
    output = re.fullmatch(rf'sw \$v0, (?P<out>{NUMBER})\(\$v1\)', rows[moved + 2][1])
    if (not all((field, offset, reset, add, output)) or rows[moved][2] != rows[read][1]
            or rows[read + 1][1] != f'lui $at, %hi({reset["symbol"]})'):
        return None
    target = [row[1] for row in rows if row[1]]
    literals = [m for row in target if (m := re.fullmatch(rf'addiu \$a1, \$zero, ({NUMBER})', row))]
    if len(literals) != 1:
        return None
    literal = integer(literals[0][1])
    if (sum(row.startswith('sw $a1, ') for row in target) != 3
            or sum(row in ('subu $v0, $a1, $v0', 'subu $a1, $a1, $v0') for row in target) != 2):
        return None
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(void \*(?P<arg>{IDENT})\)\s*$', part.clean[:part.opening])
    if not signature:
        return None
    arg = signature['arg']
    block = part.body
    begin = part.opening + 1
    sequence = re.search(
        rf'(?m)^(?P<pad>[ \t]*)(?P<ptr>{IDENT}) = M2C_FIELD\({arg}, void \*\*, (?P<base>{NUMBER})\);\n'
        rf'(?P=pad)M2C_FIELD\(&{IDENT}, s32 \*, {NUMBER}\) = 0;\n'
        rf'(?P=pad)M2C_FIELD\((?P=ptr), s32 \*, (?P<out>{NUMBER})\) = \(s32\) \('
        rf'(?P<field>M2C_FIELD\((?P=ptr), s32 \*, (?P<in>{NUMBER})\)) \+ (?P<add>{NUMBER})\);',
        block)
    if (not sequence or any(integer(sequence[k]) != integer(ref[k])
                            for k, ref in (('base', offset), ('out', output), ('in', field), ('add', add)))):
        return None
    # Replace only the repeating stored constant and the literal starting a subtraction.
    uses = [m for m in re.finditer(rf'(?: = |\(s32\) \()(?P<num>{NUMBER})(?=;| - M2C_FIELD\()', block)
            if integer(m['num']) == literal]
    if len(uses) != 4:
        return None
    pad = sequence['pad']
    init_at = begin + block.rfind('\n', 0, uses[0].start()) + 1
    stage_at = begin + block.index('\n', sequence.start()) + 1
    edits = [(begin, begin, f'\n{pad}s32 __repair_layout_limit;\n{pad}s32 __repair_layout_field;'),
             (init_at, init_at, f'{pad}__repair_layout_limit = {uses[0]["num"]};\n'),
             (stage_at, stage_at, f'{pad}__repair_layout_field = {sequence["field"]};\n'),
             (begin + sequence.start('field'), begin + sequence.end('field'), '__repair_layout_field')]
    edits.extend((begin + m.start('num'), begin + m.end('num'), '__repair_layout_limit') for m in uses)
    if len(changes) == 3:
        shift = changes[-1]
        load = re.fullmatch(rf'lw \$a1, ({NUMBER})\(\$v0\)', rows[shift][1])
        if (not load or rows[shift][2] != rows[shift][1].replace('$a1', '$a0') or rows[shift - 1][1] != rows[shift - 1][2]
                or not (call := re.fullmatch(rf'jal ({IDENT})', rows[shift - 1][1]))):
            return None
        callee = call[1]
        sites = list(calls(part, callee))
        prototype = re.search(rf'(?m)^[ \t]*M2C_UNK {callee}\((?P<arg>s32)\);[ \t]*/\* extern \*/',
                              part.source[:part.opening])
        if (len(sites) != 1 or not prototype or re.search(rf'\b{callee}\b', _blank(header))
                or not passthrough_argument_repairs._entry_a0_reaches(asm, callee)):
            return None
        call_at, call_end = sites[0]
        c_field = re.fullmatch(rf'M2C_FIELD\(M2C_FIELD\({arg}, void \*\*, ({NUMBER})\), s32 \*, ({NUMBER})\)',
                               part.clean[call_at:call_end])
        previous = re.fullmatch(rf'lw \$v0, ({NUMBER})\(\$a0\)', rows[shift - 2][1])
        if not c_field or not previous or [integer(k) for k in c_field.groups()] != [integer(previous[1]), integer(load[1])]:
            return None
        edits.extend([(*prototype.span('arg'), 'void *, s32'), (call_at, call_at, f'{arg}, ')])
    return edit(part.source, edits)


def variants(source, name, header, rows, asm):
    if not 25 <= len(rows) <= 72 or 'M2C_FIELD' not in source or not (part := view(source, name)):
        return []
    if 'bnel' in asm and (fixed := _record_scan(part, name, header, asm)):
        return [('record_scan_byte_cursors', fixed)]
    if fixed := _stage_layout(part, name, header, rows, asm):
        return [('staged_layout_constant_and_load', fixed)]
    return []
