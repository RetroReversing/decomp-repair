"""Recover a masked dispatch that feeds one pointer-and-byte call."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .shared_default_drafts import _entries, _instructions

_BASE = re.compile(
    rf'(?P<arg>{IDENT}) = (?P<mode>{IDENT}) & 0xFF; '
    rf'(?P<row>{IDENT}) = \*(?:\(s32 \*\))?\((?:\(char \*\))?&(?P<base>{IDENT}) \+ (?P<offset>{NUMBER}) '
    rf'\+ \(\((?P<bank>{IDENT}) & 0xFF\) \* 4\)\) \+ \(\((?P=row) & 0xFF\) \* 0x2C4\); '
    rf'(?P<ptr>{IDENT}) = (?P=row) \+ \(\(\((?P<col>{IDENT}) & 0xFF\) << 6\) \+ 0x2C\); '
    rf'(?P<call_label>{IDENT}): (?P<callee>{IDENT})\((?P=ptr), (?P=arg), (?P=row)\); break;'
)
_DISPATCH = re.compile(
    r'^addiu \$sp, \$sp, -0x18\naddu \$t0, \$a0, \$zero\naddu \$a0, \$a1, \$zero\n'
    r'andi \$a1, \$a0, 0xFF\nsltiu \$v0, \$a1, 0x1B\nbeqz \$v0, (?P<default>\.L\w+)\n'
    r'sw \$ra, 0x10\(\$sp\)\nsll \$v0, \$a1, 2\n'
    rf'lui \$at, %hi\((?P<table>{IDENT})\)\naddu \$at, \$at, \$v0\nlw \$v0, %lo\((?P=table)\)\(\$at\)\n'
    r'jr \$v0\nnop(?:\n|$)'
)
_RUN = (
    'andi $a1, $t0, 0xFF', 'andi $a0, $a0, 0xFF', 'sll $a0, $a0, 2', 'andi $v1, $a2, 0xFF',
    'sll $v0, $v1, 1', 'addu $v0, $v0, $v1', 'sll $v0, $v0, 2', 'subu $v0, $v0, $v1',
    'sll $v0, $v0, 4',
)
_TAIL = 'lw $ra, 0x10($sp)', 'jr $ra', 'addiu $sp, $sp, 0x18'


def _dispatch(asm):
    if '0x1B' in asm and 'subu' in asm:
        return _DISPATCH.match('\n'.join(_instructions(asm)[0]))


def applies(asm):
    return _dispatch(asm) is not None


def _body(part, name):
    prefix = re.compile(rf'\bvoid\s+{re.escape(name)}\((s32 {IDENT}(?:, s32 {IDENT}){{3}})\)\s*$')
    signature = prefix.search(part.clean, 0, part.opening)
    if not signature:
        return None
    args = tuple(re.findall(rf's32 ({IDENT})', signature[1]))
    closing = part.clean.rfind('}', part.opening, part.end)
    compact = ' '.join(part.clean[part.opening+1:closing].split())
    sections = re.split(r'\bcase (\d+): ', compact)
    values = list(map(int, sections[1::2]))
    arms = sections[2::2]
    if values != [0, 1, 2, 3, 4, 5, 22, 23, 24, 25, 26] or any(arms[:5]):
        return None
    main = _BASE.fullmatch(arms[5].strip())
    if not main or tuple(main[key] for key in ('mode', 'bank', 'col')) != (args[0], args[1], args[3]):
        return None
    local, row, ptr = main['arg'], main['row'], main['ptr']
    if len(set(args) | {local, row, ptr, main['base'], main['callee']}) != 9:
        return None
    start = re.fullmatch(rf's32 {local}; s32 {row}; u32 (?P<selector>{IDENT}); void \*{ptr}; {row} = {args[2]}; '
                         rf'(?P=selector) = {args[1]} & 0xFF; switch \((?P=selector)\) {{ ', sections[0])
    if not start:
        return None
    mode, col, base, shared = args[0], args[3], main['base'], main['call_label']
    computed = rf'{ptr} = \(\({col} & 0xFF\) << 6\) \+ \(&{base} \+ (?P<off>{NUMBER})\); '
    reload = rf'{local} = {mode} & 0xFF; goto {shared};'
    first = re.fullmatch(computed + rf'(?P<join>{IDENT}): {reload}', arms[6].strip())
    if not first:
        return None
    join = first['join']
    second = re.fullmatch(computed + rf'goto {join};', arms[7].strip())
    fixed = rf'{ptr} = &{base} \+ (?P<off>{NUMBER}); '
    others = [re.fullmatch(fixed + reload, arm.strip()) for arm in arms[8:10]]
    others.append(re.fullmatch(fixed + rf'goto {join}; }}', arms[10].strip()))
    if not second or not all(others):
        return None
    return args, main, tuple(hit['off'] for hit in (first, second, *others))


def _targets(asm, data, main, offsets):
    lines, labels = _instructions(asm)
    dispatch = _DISPATCH.match('\n'.join(lines))
    if not dispatch or tuple(lines[-3:]) != _TAIL:
        return False
    entries = _entries(data, dispatch['table'], 27)
    if not entries or any(label not in labels for label in [*entries, dispatch['default']]):
        return False
    idx = [labels[value] for value in entries]
    default = labels[dispatch['default']]
    if (default != len(lines) - 3 or idx[:6] != [13] * 6 or idx[6:22] != [default] * 16
            or idx[22:] != sorted(set(idx[22:]))):
        return False
    if tuple(lines[13:22]) != _RUN:
        return False
    callee, base, table = main['callee'], main['base'], main['offset']
    call = default - 2
    load_kind = 'andi $a1, $t0, 0xFF'
    if lines[call-1:default] != [load_kind, f'jal {callee}', 'nop']:
        return False
    if [line for line in lines if line.startswith(('jal ', 'jalr '))] != [f'jal {callee}']:
        return False
    first_arm = lines[22:idx[22]]
    if (not first_arm or first_arm[0] != f'lui $a2, %hi({base} + {table})'
            or not re.search(rf'(?m)^lw \$a2, %lo\({base} \+ (?:\()?{table}(?: & 0xFFFF\))?\)\(\$a2\)$',
                             '\n'.join(first_arm))
            or first_arm[3:8] != ['addu $v0, $v0, $v1', 'sll $v0, $v0, 2', 'andi $a0, $a3, 0xFF',
                                 'sll $a0, $a0, 6', 'addiu $a0, $a0, 0x2C']):
        return False
    def jumps_to(line, target):
        return line.startswith('j ') and labels.get(line[2:]) == target

    if (len(first_arm) != 11 or not jumps_to(first_arm[-2], call)
            or first_arm[-3] != 'addu $a2, $a2, $v0' or first_arm[-1] != 'addu $a0, $a2, $a0'):
        return False
    ends = idx[23:] + [call-1]
    for number, (start, end, off) in enumerate(zip(idx[22:], ends, offsets)):
        reg = '$v0' if number < 2 else '$a0'
        at = start + (2 if number < 2 else 0)
        expr = f'{base} + {off}'
        if lines[at:at+2] != [f'lui {reg}, %hi({expr})', f'addiu {reg}, {reg}, %lo({expr})']:
            return False
        tail = lines[at+2:end]
        if number < 2:
            if (lines[start:at] != ['andi $a0, $a3, 0xFF', 'sll $a0, $a0, 6']
                    or len(tail) != 2 or not jumps_to(tail[0], call-1) or tail[1] != 'addu $a0, $a0, $v0'):
                return False
        elif number < 4:
            if len(tail) != 2 or not jumps_to(tail[0], call) or tail[1] != load_kind:
                return False
        elif tail:
            return False
    return True


def rewrite(source, name, asm, data, header=''):
    if not data or 'goto ' not in source or not applies(asm) or not (part := view(source, name)):
        return None
    parsed = _body(part, name)
    if not parsed:
        return None
    params, main, offsets = parsed
    if not _targets(asm, data, main, offsets):
        return None
    base, callee = main['base'], main['callee']
    if re.search(rf'\b(?:{base}|{callee}|__m2c_dispatch_\w+)\b', header) or '__m2c_dispatch_' in source:
        return None
    decl = re.search(rf'\bextern M2C_UNK {base};', part.clean[:part.opening])
    prototype = re.search(rf'\bM2C_UNK {callee}\(void \*, s32, s32\);', part.clean[:part.opening])
    if not decl or not prototype or len(re.findall(rf'\b{callee}\b', part.clean)) != 2:
        return None
    if len(re.findall(rf'\b{base}\b', part.clean)) != 7:
        return None
    lo = '__m2c_dispatch_'
    mode, bank, row, col = (lo+field for field in ('mode', 'bank', 'row', 'column'))
    body = [''] + [f'    unsigned char {var} = {param} & 255;' for var, param in zip((mode, bank, row, col), params)]
    body += [f'    switch ({bank}) {{', *(f'    case {index}:' for index in range(6)),
             f'        {callee}(((unsigned char **)({base} + {main["offset"]}))[{bank}]'
             f' + {row} * 708 + (({col} << 6) + 44), {mode});', '        break;']
    for number, address in enumerate(offsets, 22):
        step = f' + ({col} << 6)' if number < 24 else ''
        body += [f'    case {number}:', f'        {callee}({base} + {integer(address)}{step}, {mode});', '        break;']
    body.extend(('    }', ''))
    closing = part.clean.rfind('}', part.opening, part.end)
    return edit(source, [(*decl.span(), f'extern unsigned char {base}[];'),
                         (*prototype.span(), f'void {callee}(unsigned char *, unsigned char);'),
                         (part.opening+1, closing, '\n'.join(body))])


def variants(source, name, asm, header, *, read_data, big_endian):
    """Read just the bounded dispatch table when repairing a compiled draft."""
    if read_data is None or 'goto ' not in source or not (dispatch := _dispatch(asm)):
        return []
    table = dispatch['table']
    data = read_data(table, 27 * 4)
    if data is None or len(data) != 27 * 4:
        return []
    order = 'big' if big_endian else 'little'
    words = [int.from_bytes(data[at:at+4], order) for at in range(0, len(data), 4)]
    directives = f'dlabel {table}\n' + '\n'.join(f'.word .L{word:08X}' for word in words)
    fixed = rewrite(source, name, asm, directives, header)
    return [('masked_switch_pointer_calls', fixed)] if fixed else []
