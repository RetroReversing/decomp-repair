"""Recover typed slot and mask tables used by a shared switch guard."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .shared_default_drafts import _entries, _instructions

_GROUPS = (((3, 5), 0x8000), ((4, 6), 0x4000), ((10,), 0x800), ((11,), 0x2000), ((9,), 0x1000))
_DISPATCH = re.compile(
    r'addiu \$v1, \$s0, -0x3\nsltiu \$v0, \$v1, 0x9\n'
    r'beqz \$v0, (?P<default>\.L\w+)\nsll \$v0, \$v1, 2\n'
    r'addu \$v0, \$v0, \$(?:fp|s8)\nlw \$v0, 0x0\(\$v0\)\njr \$v0\nnop'
)
_TABLE = re.compile(rf'lui (?P<base>\$(?:fp|s8)), %hi\((?P<table>{IDENT})\)\n'
                    r'addiu (?P=base), (?P=base), %lo\((?P=table)\)')
_PREFIX = re.compile(
    rf's32 (?P<offset>{IDENT}); s32 (?P<index>{IDENT}); s32 (?P<offset_index>{IDENT}); '
    rf's32 (?P<stride>{IDENT}); s32 (?P<flag>{IDENT}); (?P=index) = 0; '
    rf'if \(\(s32\) M2C_FIELD\((?P<obj>{IDENT}), u16 \*, 4\) > 0\) {{ '
    r'(?P=offset_index) = 0; (?P=stride) = 0; do { '
    rf'if \(\((?P<entry>\*\((?P=offset_index) \+ \(\(M2C_FIELD\(&(?P<state>{IDENT}), u8 \*, '
    rf'(?P<mode>{NUMBER})\) \* 0x22\) \+ &(?P<offsets>{IDENT})\)\)) >= 0\) && '
    rf'\((?P<mask>{IDENT}) & \*\(&(?P<masks>{IDENT}) \+ \(\(\(M2C_FIELD\(&(?P=state), u8 \*, (?P=mode)\) '
    r'\* 0x11\) \+ (?P=index)\) \* 4\)\)\)\) { switch \((?P=index)\) { '
)


def _target(lines):
    text = '\n'.join(lines)
    dispatch = _DISPATCH.search(text)
    table = _TABLE.search(text, 0, dispatch.start()) if dispatch else None
    return (dispatch, table['table']) if table else None


def applies(asm):
    return '0x24' in asm and 'sltiu' in asm and _target(_instructions(asm)[0]) is not None


def _source(part, name):
    closing = part.clean.rfind('}', part.opening, part.end)
    compact = ' '.join(part.clean[part.opening+1:closing].split())
    start = _PREFIX.match(compact)
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(([^()]*)\)\s*$', part.clean[:part.opening])
    if not start or not signature:
        return None
    formals = signature[1].split(', ')
    names = [param.rsplit(' ', 1)[-1].lstrip('*') for param in formals]
    if len(names) not in (5, 6) or len(set(names)) != len(names) or names[0] != start['obj'] or names[4] != start['mask']:
        return None
    if any(not re.fullmatch(IDENT, name) for name in names):
        return None
    obj, a, b, c, mask, *extra = names
    types = [f'void *{obj}', f's32 {a}', f'{"M2C_UNK" if extra else "s32"} {b}', f'M2C_UNK {c}', f's32 {mask}']
    if extra:
        types.append(f's32 {extra[0]}')
    if formals != types:
        return None

    flag, state = start['flag'], start['state']
    def field(offset):
        return rf'{flag} = M2C_FIELD\(&{state}, u16 \*, {offset}\) & '
    args = [f'M2C_FIELD({obj}, s32 *, 0) + {start["stride"]}', f'{a} + {start["offset"]}']
    if extra:
        args.extend((b, c, f'{extra[0]} + {start["offset"]}'))
    else:
        args.extend((f'{b} + {start["offset"]}', c))
    common = (rf'(?P<join>{IDENT}): if \({flag} == 0\) {{ default: '
              rf'{start["offset"]} = {re.escape(start["entry"])} \* 4; '
              rf'(?P<callee>{IDENT})\({re.escape(", ".join(args))}\); }} break; ')
    def labels(cases):
        return ''.join(f'case {n}: ' for n in cases)
    first_cases, first_mask = _GROUPS[0]
    first = re.match(labels(first_cases) + field(rf'(?P<flag_off>{NUMBER})') + rf'0x{first_mask:X}; ' + common, compact[start.end():])
    if not first:
        return None
    rest = ''.join(labels(cases) + field(re.escape(first['flag_off']))
                   + rf'0x{mask:X}; goto {first["join"]}; ' for cases, mask in _GROUPS[1:])
    stride, offset_index, index = (start[k] for k in ('stride', 'offset_index', 'index'))
    tail = (rf'}} }} {offset_index} \+= 2; {index} \+= 1; {stride} \+= 0x24; '
            rf'}} while \({index} < \(s32\) M2C_FIELD\({obj}, u16 \*, 4\)\); }}')
    if not re.fullmatch(rest + tail, compact[start.end()+first.end():]):
        return None
    names_in_use = {*names, start['offset'], index, offset_index, stride, flag, state,
                    start['offsets'], start['masks'], first['callee']}
    if len(names_in_use) != len(names) + 9:
        return None
    return signature, start, first, names, closing


def _verified(asm, data, source, body, extra_argument):
    lines, labels = _instructions(asm)
    found = _target(lines)
    if not found:
        return False
    dispatch, table = found
    targets = _entries(data, table, 9)
    if not targets or any(label not in labels for label in [*targets, dispatch['default']]):
        return False
    default = labels[dispatch['default']]
    masked = {case: mask for cases, mask in _GROUPS for case in cases}
    state, flag_off = source['state'], body['flag_off']
    join = None
    for number, label in enumerate(targets, 3):
        at = labels[label]
        if number not in masked:
            if at != default:
                return False
            continue
        if at >= default or at + 3 >= len(lines) or lines[at:at+2] != [f'lui $v0, %hi({state} + {flag_off})',
                                               f'lhu $v0, %lo({state} + {flag_off})($v0)']:
            return False
        flag = f'andi $v0, $v0, 0x{masked[number]:X}'
        branch = at + 2
        if number != 9:
            jump = lines[branch].removeprefix('j ')
            edge = labels.get(jump)
            if edge is None or (join is not None and edge != join):
                return False
            join = edge
            branch += 1
        elif join is None or branch + 1 != join:
            return False
        if lines[branch] != flag:
            return False
    required = {
        f'lbu $v1, %lo({state} + {source["mode"]})($v1)',
        f'lhu $v0, %lo({source["masks"]})($at)', f'addiu $s4, $s4, %lo({source["offsets"]})',
        'lhu $v0, 0x4($s3)', 'lh $v0, 0x0($v0)', 'addiu $s1, $s1, 0x2', 'addiu $s2, $s2, 0x24',
        'addu $a0, $a0, $s2',
    }
    calls = [at for at, line in enumerate(lines) if line.startswith(('jal ', 'jalr '))]
    if len(calls) != 1 or lines[calls[0]] != f'jal {body["callee"]}':
        return False
    slot = 'sw $v0, 0x10($sp)' if extra_argument else 'addu $a2, $s6, $a2'
    return (join is not None and join < len(lines) and lines[join].startswith('bnel $v0, $zero, ')
            and lines[calls[0]+1:calls[0]+2] == [slot] and required.issubset(lines))


def rewrite(source, name, asm, data, header=''):
    if not data or 'goto ' not in source or not applies(asm) or not (part := view(source, name)):
        return None
    parsed = _source(part, name)
    if not parsed:
        return None
    signature, fields, shared, names, closing = parsed
    if not _verified(asm, data, fields, shared, len(names) == 6):
        return None
    base, offsets, masks, callee = (fields['state'], fields['offsets'], fields['masks'], shared['callee'])
    symbols = (base, offsets, masks, callee)
    if '__m2c_slot_' in source + header or any(re.search(rf'\b{symbol}\b', header) for symbol in symbols):
        return None
    prefix = part.clean[:signature.start()]
    declarations = [re.search(rf'\bextern M2C_UNK {symbol};', prefix) for symbol in symbols[:3]]
    obj, a, b, c, mask, *extra = names
    old_proto = 's32, s32, M2C_UNK, M2C_UNK, s32' if extra else 's32, s32, s32, M2C_UNK'
    prototype = re.search(rf'\bM2C_UNK {callee}\({old_proto}\);', prefix)
    if not all(declarations) or not prototype or len(re.findall(rf'\b{callee}\b', part.clean)) != 2:
        return None
    if any(len(re.findall(rf'\b{symbol}\b', part.clean)) != count
           for symbol, count in ((base, 9), (offsets, 3), (masks, 2))):
        return None
    ix, stride, off = tuple('__m2c_slot_' + word for word in ('index', 'stride', 'offset'))
    mode = f'{base}[{fields["mode"]}]'
    if extra:
        mask_decl = ('typedef struct { u16 mask, reserved; } __m2c_slot_mask;\n'
                     f'extern __m2c_slot_mask {masks}[][17];')
        mask_ref = f'{masks}[{mode}][{ix}].mask'
        params = f's32 *{a}, void *{b}, s32 {c}, u32 {mask}, s32 *{extra[0]}'
        proto = 'void *, void *, void *, s32, void *'
        arguments = f'{a} + {off}, {b}, {c}, {extra[0]} + {off}'
    else:
        mask_decl = f'extern u16 {masks}[][2];'
        mask_ref = f'{masks}[{mode} * 17 + {ix}][0]'
        params = f's32 *{a}, s32 *{b}, s32 {c}, s32 {mask}'
        proto = 'u8 *, s32 *, s32 *, s32'
        arguments = f'{a} + {off}, {b} + {off}, {c}'
    body = [f'void {name}(__m2c_slot_list *{obj}, {params}) {{', f'    s32 {ix}, {stride};', f'    s16 {off};',
            f'    for ({ix} = 0; {ix} < {obj}->count; {ix}++) {{',
            f'        if ({offsets}[{mode}][{ix}] < 0) continue;',
            f'        if (!({mask} & {mask_ref})) continue;', f'        switch ({ix}) {{']
    for cases, value in _GROUPS:
        body.extend(f'        case {case}:' for case in cases)
        body.extend((f'            if ((*(u16 *)({base} + {shared["flag_off"]})) & {value}) continue;', '            break;'))
    body.extend(('        }', f'        {stride} = {ix} * 36;', f'        {off} = {offsets}[{mode}][{ix}];',
                 f'        {callee}({obj}->data + {stride}, {arguments});', '    }', '}'))
    return edit(source, [(*declarations[0].span(), f'extern u8 {base}[];'),
                         (*declarations[1].span(), f'extern s16 {offsets}[][17];'),
                         (*declarations[2].span(), mask_decl), (*prototype.span(), f'void {callee}({proto});'),
                         (signature.start(), closing + 1,
                          'typedef struct { u8 *data; u16 count; } __m2c_slot_list;\n' + '\n'.join(body))])


def variants(source, name, asm, header, *, read_data, big_endian):
    """Read the bounded table when repairing a previously compiled switch."""
    if read_data is None or 'goto ' not in source or not applies(asm):
        return []
    _, symbol = _target(_instructions(asm)[0])
    data = read_data(symbol, 36)
    if data is None or len(data) != 36:
        return []
    order = 'big' if big_endian else 'little'
    words = [int.from_bytes(data[at:at+4], order) for at in range(0, 36, 4)]
    table = f'dlabel {symbol}\n' + '\n'.join(f'.word .L{word:08X}' for word in words)
    fixed = rewrite(source, name, asm, table, header)
    return [('masked_slot_dispatch', fixed)] if fixed else []
