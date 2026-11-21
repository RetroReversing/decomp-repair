"""Reconstruct stack arrays after m2c loses the base of an evidenced local object."""

import re

from .integer_repair_support import IDENT, NUMBER, integer, view
from .measured_stack_drafts import _body, _lines
from .unaligned_stack_drafts import MEMORY

PREFIX = '__m2c_large_stack_'


def _shape(template):
    """One identifier per role, with subsequent occurrences tied to that role."""
    text = ' '.join(template.split())
    parts = re.split(r'(@[a-z]+)', text)
    seen = set()
    for i, part in enumerate(parts):
        if part.startswith('@'):
            key = part[1:]
            parts[i] = f'(?P={key})' if key in seen else f'(?P<{key}>{IDENT})'
            seen.add(key)
        else:
            parts[i] = re.escape(part)
    return re.compile(''.join(parts))


def _copy_fields(offsets, kinds):
    fields = []
    for offset, field in zip(offsets, kinds):
        n = str(offset) if offset < 10 else f'0x{offset:X}'
        fetch = f'M2C_FIELD(@src, {field} *, {n})'
        rhs = f'M2C_UNALIGNED32({fetch})' if field == 'M2C_UNK' else f'({field}) {fetch}'
        fields.append(f'M2C_FIELD(@dst, {field} *, {n}) = {rhs};')
    return ' '.join(fields)


BLOB = _shape('''
    @src = &@base;
    @dst = sp;
    if (((s32) sp | (s32) &@base) & 3) {
        do { '''+_copy_fields([0,4,8,12], ('M2C_UNK',)*4)+'''
            @src += 0x10;
            @dst += 0x10;
        } while (@src != (&@base + 0x20));
    } else {
        do { '''+_copy_fields([0,4,8,12], ('s32',)*4)+'''
            @src += 0x10;
            @dst += 0x10;
        } while (@src != (&@base + 0x20));
    }
    '''+_copy_fields([0,4,8,9], ('M2C_UNK','M2C_UNK','s8','s8'))+'''
    if (*@flag != 3) {
        return M2C_FIELD((sp + @index), u8 *, -0x2E);
    }
    return *(sp + @index);
''')

MATRIX = _shape('''
    @leftrow = @left;
    @outrow = @out;
    @row = 0;
    @localrow = sp;
    do {
        @column = 0;
        @cell = @localrow;
        @columnbytes = 0;
    @columns:
        *@cell = 0.0f;
        @inner = 0;
        @leftcell = @leftrow;
        @rightrow = @right;
    @innerloop:
        @product = *@leftcell * *(@columnbytes + @rightrow);
        @leftcell += 4;
        @rightrow += 0x10;
        @inner += 1;
        *@cell += @product;
        if (@inner < 4) { goto @innerloop; }
        @cell += 4;
        @column += 1;
        @columnbytes += 4;
        if (@column < 4) { goto @columns; }
        @leftrow += 0x10;
        @row += 1;
        @localrow += 0x10;
    } while (@row < 4);
    @copyrow = 0;
    @copybase = sp;
    do {
        @copycol = 0;
        @write = @outrow;
        @read = @copybase;
    @copycolumns:
        @value = *@read;
        @read += 4;
        @copycol += 1;
        *@write = @value;
        @write += 4;
        if (@copycol < 4) { goto @copycolumns; }
        @copybase += 0x10;
        @copyrow += 1;
        @outrow += 0x10;
    } while (@copyrow < 4);
''')


def _frame(lines, size):
    pattern = re.compile(rf'addiu\s+\$sp,\s*\$sp,\s*(-?{NUMBER})')
    moves = [hit[1] for op in lines if (hit := pattern.fullmatch(op))]
    return len(moves) == 2 and moves[0].startswith('-') and not moves[1].startswith('-') and (
        integer(moves[0][1:]) == integer(moves[1]) == size)


def _transfers(lines, loads, stores, offsets):
    ops = loads + stores
    size = len(ops)
    for pos, line in enumerate(lines):
        if not line.startswith(loads[0]) or pos+size > len(lines):
            continue
        insns = [MEMORY.fullmatch(item) for item in lines[pos:pos+size]]
        if not all(insns):
            continue
        kinds, regs, disps, bases = zip(*(hit.groups() for hit in insns))
        n = len(loads)
        if (kinds == ops and regs[:n] == regs[n:] and len(set(bases[:n])) == len(set(bases[n:])) == 1
                and all(regs[i-1] == regs[i] for i, kind in enumerate(loads) if kind == 'lwr')
                and bases[0] != bases[n] and not set(bases) & set(regs)
                and [integer(off or '0') for off in disps] == offsets * 2):
            return bases[0], bases[n]
    return None


def _blob_copy(lines):
    if not _frame(lines, 48):
        return False
    lanes = _transfers(lines, ('lwl', 'lwr')*4, ('swl', 'swr')*4, [0,3,4,7,8,11,12,15])
    if not lanes or lanes != _transfers(lines, ('lw',)*4, ('sw',)*4, [0,4,8,12]):
        return False
    if lanes != _transfers(lines, ('lwl','lwr','lwl','lwr','lb','lb'), ('swl','swr','swl','swr','sb','sb'), [0,3,4,7,8,9]):
        return False
    src, dst = map(re.escape, lanes)
    return (any(re.fullmatch(rf'(?:addu|or)\s+{dst},\s*\$sp,\s*\$zero', op) for op in lines)
            and sum(bool(re.fullmatch(rf'addiu\s+\$\w+,\s*{src},\s*(?:0x20|32)', op)) for op in lines) == 2
            and any(re.fullmatch(r'lbu\s+\$\w+,\s*-(?:0x2[Ee]|46)\(\$\w+\)', op) for op in lines))


def _matrix_copy(lines):
    if not _frame(lines, 64):
        return False
    opcodes = [line.split(maxsplit=1)[0] for line in lines]
    return (opcodes.count('lwc1') == 4 and opcodes.count('swc1') == 2
            and opcodes.count('mul.s') == opcodes.count('add.s') == 1
            and sum(bool(re.fullmatch(r'(?:addu|or)\s+\$\w+,\s*\$sp,\s*\$zero', op)) for op in lines) == 2
            and sum(bool(re.fullmatch(r'slti\s+\$\w+,\s*\$\w+,\s*(?:0x)?4', op)) for op in lines) == 5)


def applies(asm):
    """Invalidate old drafts only for witnessed bulk copies or matrix frames."""
    return (('lwr' in asm and 'swr' in asm and _blob_copy(_lines(asm)))
            or ('mul.s' in asm and 'swc1' in asm and _matrix_copy(_lines(asm))))


def _blob(part, name, context, locals_, body, end, lines):
    hit = BLOB.fullmatch(body)
    signature = re.search(rf'\bu8\s+{re.escape(name)}\(s8 ({IDENT})\)\s*$', part.clean[:part.opening])
    if (not hit or not signature or signature[1] != hit['index']
            or locals_ != {hit['src']: 'M2C_UNK*', hit['dst']: 'void*'} or not _blob_copy(lines)):
        return None
    base, flag = hit['base'], hit['flag']
    decl = re.search(rf'\bextern M2C_UNK {base};', part.clean[:signature.start()])
    if (not decl or re.search(rf'\b{base}\b', context) or len(re.findall(rf'\b{base}\b',part.clean)) != 5
            or not re.search(rf'\bextern u8 \*{flag};', part.clean[:signature.start()])):
        return None
    p = PREFIX
    return (part.source[:decl.start()] + f'extern u8 {base}[];' + part.source[decl.end():signature.start()]
            + f'''typedef struct {{ u8 bytes[42]; }} {p}block_t;
{signature[0].strip()} {{
    u8 {p}buffer[48];

    *({p}block_t *){p}buffer = *({p}block_t *){base};
    if (*{flag} == 3) {{
        return {p}buffer[{hit['index']}];
    }}
    return {p}buffer[{hit['index']} - 46];
}}''' + part.source[end+1:])


def _matrix(part, name, locals_, body, end, lines):
    hit = MATRIX.fullmatch(body)
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(f32 \*({IDENT}), s32 ({IDENT}), f32 \*({IDENT})\)\s*$',
                          part.clean[:part.opening])
    if not hit or not signature or signature.groups() != (hit['left'],hit['right'],hit['out']) or not _matrix_copy(lines):
        return None
    widths = {'f32*': ('leftrow','outrow','localrow','cell','leftcell','copybase','write','read'),
              'f32': ('product','value'), 's32': ('row','column','columnbytes','inner','rightrow','copyrow','copycol')}
    types = {hit[key]: width for width, keys in widths.items() for key in keys}
    if len(types) != 17 or {hit['left'], hit['right'], hit['out']} & types.keys() or types != locals_:
        return None
    p = PREFIX
    return (part.source[:part.opening+1] + f'''
    f32 (*{p}left)[4] = (f32 (*)[4]){hit['left']};
    f32 (*{p}right)[4] = (f32 (*)[4]){hit['right']};
    f32 (*{p}out)[4] = (f32 (*)[4]){hit['out']};
    int {p}i, {p}j, {p}k;
    f32 {p}result[4][4];

    for ({p}i = 0; {p}i < 4; {p}i++) {{
        for ({p}j = 0; {p}j < 4; {p}j++) {{
            {p}result[{p}i][{p}j] = 0.0f;
            for ({p}k = 0; {p}k < 4; {p}k++) {{
                {p}result[{p}i][{p}j] += {p}left[{p}i][{p}k] * {p}right[{p}k][{p}j];
            }}
        }}
    }}
    for ({p}i = 0; {p}i < 4; {p}i++) {{
        for ({p}j = 0; {p}j < 4; {p}j++) {{
            {p}out[{p}i][{p}j] = {p}result[{p}i][{p}j];
        }}
    }}
}}''' + part.source[end+1:])


def rewrite(source, name, asm, context=''):
    if (' = sp;' not in source or PREFIX in source or PREFIX in context
            or re.search(r'^\s*#\s*define\s+bytes\b',source+'\n'+context,re.M)):
        return None
    part = view(source, name)
    if not part:
        return None
    locals_, body, end = _body(part)
    lines = _lines(asm)
    return _blob(part, name, context, locals_, body, end, lines) or _matrix(part, name, locals_, body, end, lines)
