"""Measured MIPS scalar updates whose allocation depends on source sequencing."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips_returns import instructions
from .pattern_repairs import close

_RELOC = re.compile(
    rf'lui (?P<address>\$\w+), %hi\((?P<symbol>{IDENT})\)\n'
    r'addiu (?P=address), (?P=address), %lo\((?P=symbol)\)\n'
    r'lbu (?P<value>\$\w+), (?:0)?\((?P=address)\)\n'
    r'addiu (?P=value), (?P=value), (?P<delta>-\d+)\n'
    r'jr \$ra\nsb (?P=value), (?:0)?\((?P=address)\)'
)
_PACK = '''
andi $v0, $a3, 255
andi $a2, $a2, 255
sll $a2, $a2, 8
addu $v0, $v0, $a2
andi $a1, $a1, 255
sll $a1, $a1, 16
addu $v0, $v0, $a1
sll $a0, $a0, 24
jr $ra
addu $v0, $v0, $a0
'''.strip()


def variants(source, name, header, toolchain, rows, asm):
    count = sum(marker != ' ' for marker, _, _ in rows)
    if count not in (4, 5):
        return []
    if toolchain == 'ido-5.3' and count == 5 and '-=' in source:
        label, candidate = 'staged_global_byte_decrement', _global_byte(source, name, header, asm)
    elif toolchain == 'gcc-2.7.2-kmc' and count == 5 and '<<' in source:
        label, candidate = 'staged_packed_bytes', _packed_bytes(source, name, header, asm)
    elif toolchain == 'gcc-2.7.2-kmc' and count == 4 and 'M2C_FIELD' in source:
        label, candidate = 'decrement_local_before_byte_store', _field_store(source, name, rows)
    else:
        return []
    return [(label, candidate)] if candidate else []


def _ops(asm):
    text = '\n'.join(' '.join(row.split()) for row in instructions(asm))
    return re.sub(r'(?<!\w)-?0x[\da-fA-F]+\b', lambda m: str(int(m[0], 16)), text)


def _global_byte(source, name, header, asm):
    target = _RELOC.fullmatch(_ops(asm))
    if not target or target['address'] == target['value']:
        return None
    part = view(source, name)
    if not part or '__repair_byte_value' in source + header:
        return None
    symbol = target['symbol']
    end = close(part.clean, part.opening, '{', '}')
    if not end or not re.search(rf'\bextern\s+u8\s+{symbol}\s*;', part.clean[:part.opening]):
        return None
    if re.search(rf'\bvolatile\b[^;]*\b{symbol}\b', header) or re.search(rf'(?m)^\s*#\s*define\s+{symbol}\b', header):
        return None
    update = re.fullmatch(rf'\s*{symbol}\s*-=\s*({NUMBER})\s*;\s*', part.clean[part.opening + 1:end - 1])
    count = -int(target['delta'])
    if not update or integer(update[1]) != count:
        return None
    body = f'\n    s32 __repair_byte_value;\n    __repair_byte_value = {symbol};\n'
    body += f'    __repair_byte_value -= {count};\n    {symbol} = __repair_byte_value;\n'
    return edit(source, [(part.opening + 1, end - 1, body)])


def _packed_bytes(source, name, header, asm):
    if _ops(asm) != _PACK or '__repair_pack_' in source + header:
        return None
    part = view(source, name)
    if not part:
        return None
    formals = r'\s*,\s*'.join(rf's32\s+({IDENT})' for _ in range(4))
    signature = re.search(rf'\bs32\s+{re.escape(name)}\s*\({formals}\)\s*$', part.clean[:part.opening])
    end = close(part.clean, part.opening, '{', '}')
    if not signature or not end:
        return None
    a, b, c, d = signature.groups()
    mask = r'(?:0x[fF][fF]|255)'
    expression = (rf'return \({d} & {mask}\) \+ \(\({c} & {mask}\) << (?:0x8|8)\) \+ '
                  rf'\(\({b} & {mask}\) << (?:0x10|16)\) \+ \({a} << (?:0x18|24)\);')
    if not re.fullmatch(expression, ' '.join(part.clean[part.opening + 1:end - 1].split())):
        return None
    body = f"""
    s32 __repair_pack_value, __repair_pack_high, __repair_pack_mid_high, __repair_pack_mid_low;
    __repair_pack_value = {d} & 0xFF;
    __repair_pack_mid_low = {c} & 0xFF;
    __repair_pack_mid_low <<= 8;
    __repair_pack_value += __repair_pack_mid_low;
    __repair_pack_mid_high = {b} & 0xFF;
    __repair_pack_mid_high <<= 16;
    __repair_pack_value += __repair_pack_mid_high;
    __repair_pack_high = {a} << 24;
    __repair_pack_value += __repair_pack_high;
    return __repair_pack_value;
"""
    return edit(source, [(part.opening + 1, end - 1, body)])


def _field_store(source, name, rows):
    changed = [i for i, row in enumerate(rows) if row[0] != ' ']
    high, low, one, store = changed
    if (high < 2 or low != high + 1 or one != low + 1 or store != one + 2
            or rows[high - 2][1] != 'addiu $v0, $v0, -1' or not rows[store - 1][1].startswith('jal ')):
        return None
    anchor = re.fullmatch(rf'lui \$v0, %hi\(({IDENT})\)', rows[high][1])
    constant = rows[one][1] == 'addiu $v1, $zero, 1'
    write = re.fullmatch(rf'sb \$v1, ({NUMBER})\(\$v0\)', rows[store][1])
    decrement = re.fullmatch(rf'sb \$v0, ({NUMBER})\(\$v1\)', rows[high - 1][1])
    if not anchor or not constant or not write or not decrement:
        return None
    base = anchor[1]
    if rows[low][1] != f'lw $v0, %lo({base})($v0)':
        return None
    for i in changed:
        swapped = re.sub(r'\$v[01]\b', lambda m: '$v0' if m[0] == '$v1' else '$v1', rows[i][1])
        if rows[i][2] != swapped:
            return None
    part = view(source, name)
    if not part:
        return None
    shape = re.compile(
        rf'(?m)^[ \t]*M2C_FIELD\(\s*{base},\s*u8\s*\*,\s*(?P<decrement>{NUMBER})\)\s*=\s*'
        rf'(?P<expression>\(u8\)\s*\((?P<local>{IDENT})\s*-\s*1\))\s*;\s*'
        rf'M2C_FIELD\(\s*{base},\s*[su]8\s*\*,\s*(?P<write>{NUMBER})\)\s*=\s*1\s*;')
    for match in shape.finditer(part.clean, part.opening + 1, part.end):
        local = match['local']
        before, after = part.clean[part.opening + 1:match.start()], part.clean[match.end():part.end]
        if (integer(match['decrement']) == integer(decrement[1]) and integer(match['write']) == integer(write[1])
                and integer(match['decrement']) != integer(match['write'])
                and re.search(rf'(?m)^\s*u8\s+{local}\s*;', before)
                and not re.search(rf'&\s*{local}\b', before)
                and not re.search(rf'\b{local}\b', after)):
            return edit(source, [(*match.span('expression'), '--' + local)])
    return None
