from decomprepair.large_stack_drafts import applies, rewrite


def _fields(types):
    fields = []
    for offset, kind in types:
        read = f'M2C_FIELD(src, {kind} *, {offset})'
        value = f'M2C_UNALIGNED32({read})' if kind == 'M2C_UNK' else f'({kind}) {read}'
        fields.append(f'M2C_FIELD(dst, {kind} *, {offset}) = {value};')
    return ' '.join(fields)


def _transfer(ops, offsets, base):
    return '\n'.join(f'{op} $t{i}, {offset}({base})' for op, offset, i in zip(ops, offsets, (
        (0,0,1,1,2,2,3,3) if len(ops) == 8 else (0,0,1,1,2,3) if len(ops) == 6 else (0,1,2,3))))


def test_bulk_copy_requires_matching_aligned_unaligned_and_tail_transfers():
    word_offsets = ['0','4','8','0xC']
    paired = [0,3,4,7,8,11,12,15]
    asm = '\n'.join((
        'addiu $sp, $sp, -48', 'addu $a3, $sp, $zero',
        'addiu $a0, $a2, 32', _transfer(('lwl','lwr')*4, paired, '$a2'),
        _transfer(('swl','swr')*4, paired, '$a3'),
        'addiu $a0, $a2, 32', _transfer(('lw',)*4, word_offsets, '$a2'),
        _transfer(('sw',)*4, word_offsets, '$a3'),
        _transfer(('lwl','lwr','lwl','lwr','lb','lb'), [0,3,4,7,8,9], '$a2'),
        _transfer(('swl','swr','swl','swr','sb','sb'), [0,3,4,7,8,9], '$a3'),
        'lbu $v0, -46($v0)', 'addiu $sp, $sp, 48',
    ))
    draft = f'''
extern M2C_UNK backing;
extern u8 *mode;
u8 f(s8 index) {{
    M2C_UNK *src;
    void *dst;
    src = &backing;
    dst = sp;
    if (((s32) sp | (s32) &backing) & 3) {{
        do {{
            {_fields(zip(word_offsets, ('M2C_UNK',)*4))}
            src += 0x10;
            dst += 0x10;
        }} while (src != (&backing + 0x20));
    }} else {{
        do {{
            {_fields(zip(word_offsets, ('s32',)*4))}
            src += 0x10;
            dst += 0x10;
        }} while (src != (&backing + 0x20));
    }}
    {_fields(zip((0,4,8,9), ('M2C_UNK','M2C_UNK','s8','s8')))}
    if (*mode != 3) {{
        return M2C_FIELD((sp + index), u8 *, -0x2E);
    }}
    return *(sp + index);
}}
'''
    assert applies(asm)
    candidate = rewrite(draft, 'f', asm)
    assert 'bytes[42]' in candidate and 'buffer[48]' in candidate
    assert 'extern u8 backing[];' in candidate
    assert 'return __m2c_large_stack_buffer[index - 46];' in candidate
    assert not rewrite(draft, 'f', asm.replace('sb $t3, 9($a3)', 'sb $t3, 10($a3)'))
    assert not rewrite(draft, 'f', asm, 'extern u8 backing[42];')
    assert not rewrite(draft.replace('dst += 0x10;', 'dst += 0x20;'), 'f', asm)


def test_matrix_requires_full_multiply_then_copy_and_preserves_parameter_types():
    floats = ('leftrow','outrow','localrow','cell','leftcell','copybase','write','read')
    counters = ('row','column','columnbytes','inner','rightrow','copyrow','copycol')
    declarations = ' '.join(f'f32 *{n};' for n in floats)
    declarations += ' f32 product; f32 value; ' + ' '.join(f's32 {n};' for n in counters)
    source = '''
void f(f32 *a, s32 b, f32 *dst) {
    DECLARATIONS
    leftrow = a;
    outrow = dst;
    row = 0;
    localrow = sp;
    do {
        column = 0;
        cell = localrow;
        columnbytes = 0;
    columns:
        *cell = 0.0f;
        inner = 0;
        leftcell = leftrow;
        rightrow = b;
    multiply:
        product = *leftcell * *(columnbytes + rightrow);
        leftcell += 4;
        rightrow += 0x10;
        inner += 1;
        *cell += product;
        if (inner < 4) { goto multiply; }
        cell += 4;
        column += 1;
        columnbytes += 4;
        if (column < 4) { goto columns; }
        leftrow += 0x10;
        row += 1;
        localrow += 0x10;
    } while (row < 4);
    copyrow = 0;
    copybase = sp;
    do {
        copycol = 0;
        write = outrow;
        read = copybase;
    copycolumns:
        value = *read;
        read += 4;
        copycol += 1;
        *write = value;
        write += 4;
        if (copycol < 4) { goto copycolumns; }
        copybase += 0x10;
        copyrow += 1;
        outrow += 0x10;
    } while (copyrow < 4);
}
'''.replace('DECLARATIONS', declarations)
    instructions = '''addiu $sp, $sp, -64
addu $t0, $sp, $zero
addu $t1, $sp, $zero
mul.s $f0, $f0, $f2
add.s $f0, $f0, $f2
'''+('lwc1 $f0, 0($a0)\n'*4)+('swc1 $f0, 0($a1)\n'*2)+(
    'slti $v0, $a0, 4\n'*5)+'addiu $sp, $sp, 64\n'
    assert applies(instructions)
    candidate = rewrite(source, 'f', instructions)
    assert 'void f(f32 *a, s32 b, f32 *dst)' in candidate
    assert 'result[4][4]' in candidate
    assert 'out[__m2c_large_stack_i][__m2c_large_stack_j] = __m2c_large_stack_result' in candidate
    assert not rewrite(source, 'f', instructions.replace('mul.s', 'div.s'))
    assert not rewrite(source.replace('*write = value;', '*write = product;'), 'f', instructions)
