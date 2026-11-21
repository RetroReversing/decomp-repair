"""Recover typed KMC buffer walks and address-table storage."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .pattern_repairs import close
from .shared_default_drafts import _instructions

_HALFWORDS = re.compile(
    r'''andi \$a0, \$a0, 65535
sll \$v0, \$a0, 1
addu \$v0, \$v0, \$a0
sll \$v0, \$v0, 3
addu \$v0, \$v0, \$a0
sll \$v0, \$v0, 2
lui \$at, %hi\((?P<buffers>\w+)\)
addu \$at, \$at, \$v0
sw \$a1, %lo\((?P=buffers)\)\(\$at\)
addu \$t0, \$zero, \$zero
andi \$a2, \$a2, 255
lui \$v0, %hi\((?P<pages>\w+)\)
addiu \$v0, \$v0, %lo\((?P=pages)\)
sll \$a2, \$a2, 2
addu \$a2, \$a2, \$v0
andi \$a3, \$a3, 255
sll \$a3, \$a3, 2
sll \$v1, \$t0, 1
addu \$a0, \$v1, \$a1
lw \$v0, 0\(\$a2\)
addu \$v0, \$a3, \$v0
lw \$v0, 0\(\$v0\)
addu \$v1, \$v1, \$v0
lhu \$v0, 0\(\$v1\)
sh \$v0, 0\(\$a0\)
addiu \$t0, \$t0, 1
slti \$v0, \$t0, 16
bnel \$v0, \$zero, @18
sll \$v1, \$t0, 1
jr \$ra
nop''')
_BANK = re.compile(
    r'''addiu \$sp, \$sp, -48
sw \$s2, 32\(\$sp\)
addu \$s2, \$a0, \$zero
sw \$s3, 36\(\$sp\)
addu \$s3, \$s2, \$zero
sw \$ra, 44\(\$sp\)
sw \$s4, 40\(\$sp\)
sw \$s1, 28\(\$sp\)
sw \$s0, 24\(\$sp\)
lh \$v1, 0\(\$s2\)
addiu \$v0, \$zero, (?P<tag>\d+)
bne \$v1, \$v0, @29
addu \$s4, \$a1, \$zero
lh \$v0, 2\(\$s2\)
blez \$v0, @29
addu \$s1, \$zero, \$zero
addu \$s0, \$s2, \$zero
lw \$v0, 4\(\$s0\)
addu \$a0, \$v0, \$s3
beqz \$a0, @24
sw \$a0, 4\(\$s0\)
addu \$a1, \$s3, \$zero
jal (?P<call>\w+)
addu \$a2, \$s4, \$zero
lh \$v0, 2\(\$s2\)
addiu \$s1, \$s1, 1
slt \$v0, \$s1, \$v0
bnez \$v0, @17
addiu \$s0, \$s0, 4
lw \$ra, 44\(\$sp\)
lw \$s4, 40\(\$sp\)
lw \$s3, 36\(\$sp\)
lw \$s2, 32\(\$sp\)
lw \$s1, 28\(\$sp\)
lw \$s0, 24\(\$sp\)
jr \$ra
addiu \$sp, \$sp, 48''')


def _target(asm):
    if not asm or ('lhu' not in asm and 'jal' not in asm):
        return None
    lines, labels = _instructions(asm)
    if len(lines) not in (31, 37):
        return None
    rows = []
    for row in normalized_integer_lines(lines):
        if row.startswith(('beqz ', 'bne ', 'bnez ', 'bnel ', 'blez ')):
            op, _, label = row.rpartition(', ')
            if label not in labels:
                return None
            row = f'{op}, @{labels[label]}'
        rows.append(row)
    text = '\n'.join(rows)
    for family, pattern in (('kmc_nested_halfword_table', _HALFWORDS), ('kmc_typed_relocation_walk', _BANK)):
        if match := pattern.fullmatch(text):
            return family, match
    return None


def applies(asm):
    return _target(asm) is not None


def variants(source, name, asm, header=''):
    if not source or '_m2c_buffer_' in source + header or not (target := _target(asm)):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    head, body = part.clean[:part.opening], ' '.join(part.clean[part.opening + 1:end - 1].split())
    family, match = target
    parser = _halfwords if family == 'kmc_nested_halfword_table' else _bank
    changes = parser(name, head, body, end, header, match)
    return [(family, edit(source, changes))] if changes else []


def _halfwords(name, head, body, end, header, match):
    sig = re.search(rf'\bvoid\s+{re.escape(name)}\(s32 ({IDENT}), s32 ({IDENT}), s32 ({IDENT}), s32 ({IDENT})\)\s*$', head)
    if not sig or re.search(rf'\b{re.escape(name)}\s*\(', header + head[:sig.start()]):
        return None
    mode, out, page, entry = sig.groups()
    buffers, pages = match['buffers'], match['pages']
    code = re.fullmatch(
        rf's32 (?P<offset>{IDENT}); s32 (?P<index>{IDENT}); '
        rf'\*\(&{buffers} \+ \(\({mode} & 0xFFFF\) \* 0x64\)\) = {out}; '
        rf'(?P=index) = 0; do \{{ (?P=offset) = (?P=index) \* 2; '
        rf'\*\((?P=offset) \+ {out}\) = \*\((?P=offset) \+ \*\(\(\({entry} & 0xFF\) \* 4\) \+ '
        rf'\*\(\(\({page} & 0xFF\) \* 4\) \+ &{pages}\)\)\); '
        r'(?P=index) \+= 1; \} while \((?P=index) < 0x10\);',
        body)
    if not code or re.search(rf'\b(?:{buffers}|{pages})\b', header):
        return None
    declarations = []
    for symbol, kind in ((buffers, 'u8'), (pages, 'void *')):
        stub = re.search(rf'(?m)^extern M2C_UNK {symbol};[ \t]*$', head)
        if not stub:
            return None
        declarations.append((*stub.span(), f'extern {kind} {symbol}[];'))
    i = code['index']
    rewritten = f'''void {name}(s32 {mode}, u16 *{out}, s32 {page}, s32 {entry}) {{
    s32 {i};
    *(u16 **)&{buffers}[({mode} & 0xFFFF) * 100] = {out};
    {i} = 0;
    do {{
        {out}[{i}] = ((u16 *)((void **){pages}[{page} & 255])[{entry} & 255])[{i}];
        {i} += 1;
    }} while ({i} < 16);
}}'''
    return declarations + [(sig.start(), end, rewritten)]


def _bank(name, head, body, end, header, match):
    sig = re.search(rf'\bvoid\s+{re.escape(name)}\(void \*({IDENT}), M2C_UNK ({IDENT})\)\s*$', head)
    if not sig or re.search(rf'\b{re.escape(name)}\s*\(', header + head[:sig.start()]):
        return None
    arg, ident = sig.groups()
    call = match['call']
    code = re.fullmatch(
        rf's32 (?P<i>{IDENT}); void \*(?P<tmp>{IDENT}); void \*(?P<cursor>{IDENT}); '
        rf'if \(M2C_FIELD\({arg}, s16 \*, 0\) == (?P<tag>{NUMBER})\) \{{ '
        rf'(?P=i) = 0; if \(M2C_FIELD\({arg}, s16 \*, 2\) > 0\) \{{ (?P=cursor) = {arg}; do \{{ '
        rf'(?P=tmp) = M2C_FIELD\((?P=cursor), void \*\*, 4\) \+ {arg}; '
        rf'M2C_FIELD\((?P=cursor), void \*\*, 4\) = (?P=tmp); '
        rf'if \((?P=tmp) != NULL\) \{{ {call}\((?P=tmp), {arg}, {ident}\); \}} '
        rf'(?P=i) \+= 1; (?P=cursor) \+= 4; \}} while \((?P=i) < M2C_FIELD\({arg}, s16 \*, 2\)\); \}} \}}',
        body)
    if not code or integer(code['tag']) != int(match['tag']):
        return None
    stub = re.search(rf'(?m)^M2C_UNK {call}\(void \*, void \*, M2C_UNK\);[^\n]*', head)
    if not stub or re.search(rf'\b{call}\s*\(', header):
        return None
    rewritten = f'''typedef struct {{ s16 tag; s16 count; u32 slots[1]; }} _m2c_buffer_banks;
void {name}(_m2c_buffer_banks *{arg}, s32 {ident}) {{
    _m2c_buffer_banks *_m2c_buffer_obj;
    u32 _m2c_buffer_base;
    s32 _m2c_buffer_table;
    s32 _m2c_buffer_i;
    _m2c_buffer_obj = {arg};
    _m2c_buffer_base = (u32){arg};
    _m2c_buffer_table = {ident};
    if (_m2c_buffer_obj->tag == {code['tag']}) {{
        for (_m2c_buffer_i = 0; _m2c_buffer_i < _m2c_buffer_obj->count; _m2c_buffer_i++) {{
            _m2c_buffer_obj->slots[_m2c_buffer_i] += _m2c_buffer_base;
            if (_m2c_buffer_obj->slots[_m2c_buffer_i] != 0) {{
                {call}((void *)_m2c_buffer_obj->slots[_m2c_buffer_i], _m2c_buffer_base, _m2c_buffer_table);
            }}
        }}
    }}
}}'''
    return [(*stub.span(), f'extern void {call}(void *, u32, s32);'), (sig.start(), end, rewritten)]
