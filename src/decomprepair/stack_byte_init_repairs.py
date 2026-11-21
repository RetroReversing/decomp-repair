"""Keep a byte initializer inside the stack buffer passed to two measured calls."""

import re

from .integer_repair_support import IDENT, calls, edit, integer, split_args, view

NUM = r'(?:0x[0-9a-fA-F]+|\d+)'
FAMILY = 'measured_stack_buffer_byte_init'


def variants(source, name, header, rows):
    changed = [i for i, (mark, _, _) in enumerate(rows) if mark != ' ']
    if len(changed) != 1:
        return []
    row = changed[0]
    marker, instruction, previous = rows[row]
    if marker != '<' or previous or row < 3 or row + 8 >= len(rows):
        return []
    store = re.fullmatch(rf'sb \$zero, ({NUM})\(\$sp\)', instruction)
    base = re.fullmatch(rf'addiu \$a0, \$sp, ({NUM})', rows[row-3][1])
    format_load = re.fullmatch(rf'lui \$a1, %hi\(({IDENT})\)', rows[row-2][1])
    call = re.fullmatch(rf'jal ({IDENT})', rows[row+1][1])
    use = re.fullmatch(rf'jal ({IDENT})', rows[row+6][1])
    if (not store or not base or not format_load or not call or not use or call[1] == use[1]
            or rows[row-1][1] != f'addiu $a1, $a1, %lo({format_load[1]})'):
        return []
    receiver = re.fullmatch(rf'addiu \$a3, \$sp, ({NUM})', rows[row+7][1])
    if not receiver or integer(receiver[1]) != integer(base[1]):
        return []
    saved = [integer(hit[1]) for _, text, _ in rows[:row-3]
             if (hit := re.fullmatch(rf'sw \$(?:ra|s[0-7]), ({NUM})\(\$sp\)', text))]
    if not saved:
        return []
    start, slot = integer(base[1]), integer(store[1])
    size = min(saved) - start
    if start < 16 or start % 4 or not 4 <= slot - start < size or not 5 <= size <= 64:
        return []

    local = '__repair_print_buffer'
    if local in source + header or not (part := view(source, name)):
        return []
    buf, byte = f'sp{start:X}', f'sp{slot:X}'
    declarations = re.search(rf'(?m)^[ \t]*(?P<decl>M2C_UNK {buf};\n[ \t]*s8 {byte};)', part.clean)
    initialize = re.search(rf'(?m)^[ \t]*(?P<init>{byte} = 0;)', part.clean)
    if (not declarations or not initialize or not part.opening < declarations.start() < initialize.start() < part.end
            or len(re.findall(rf'\b{buf}\b', part.body)) != 3 or len(re.findall(rf'\b{byte}\b', part.body)) != 2):
        return []
    init_end = initialize.end()
    edits = [(*declarations.span('decl'), f'char {local}[{size}];'),
             (*initialize.span('init'), f'{local}[{slot-start}] = 0;')]
    for callee, pos in ((call[1], 0), (use[1], 3)):
        sites = list(calls(part, callee))
        if len(sites) != 1 or sites[0][0] <= init_end:
            return []
        a,b = sites[0]
        args = split_args(part.clean[a:b])
        if pos >= len(args):
            return []
        x,y = args[pos]
        raw = part.clean[a+x:a+y]
        if raw.strip() != f'&{buf}':
            return []
        if pos == 0:
            x1,y1 = args[1] if len(args) > 1 else (0,0)
            if part.clean[a+x1:a+y1].strip() != f'&{format_load[1]}':
                return []
        init_end = b
        edits.append((a+x+len(raw)-len(raw.lstrip()), a+y, f'(M2C_UNK *){local}'))
    return [(FAMILY, edit(source, edits))]
