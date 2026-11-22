from decomprepair import measured_kmc_addresses as repair


def measured(trace, change=0):
    return [('r', line, 'different operand') if i == change else (' ', line, line)
            for i, line in enumerate(trace.splitlines())]


def test_indexed_context_stages_byte_displacement_and_preserves_stride():
    rows = measured('''lui $v1, %hi(state)
lw $v1, %lo(state)($v1)
andi $a0, $a0, 255
sll $v0, $a0, 1
addu $v0, $v0, $a0
sll $v0, $v0, 3
addu $v1, $v1, $v0
lw $v0, 96($v1)
xori $v0, $v0, 2
jr $ra
sltiu $v0, $v0, 1''')
    rows.insert(0, ('o', '', 'andi $a0, $a0, 255'))
    source = '''
extern s32 state;
s32 ready(s32 port) {
    return M2C_FIELD((state + ((port & 0xFF) * 24)), s32 *, 96) == 2;
}
'''
    [(family, fixed)] = repair.variants(source, 'ready', '', rows)
    assert family == 'staged_indexed_context'
    assert 'extern s8 *state;' in fixed
    assert '__repair_address_offset = (port & 0xFF) * 24;' in fixed
    assert not repair.variants(source, 'ready', 'extern s32 state;', rows)
    assert not repair.variants(source.replace('* 24', '* 4'), 'ready', '', rows)


def test_inline_sum_keeps_loaded_base_and_displacement_separate():
    trace = repair._INLINE.pattern.replace(r'\n', '\n').replace('\\', '')
    for key, generic, value in (
        ('base', '[A-Za-z_]w*', 'ctx'), ('left', 'd+', '16'), ('right', 'd+', '14'),
        ('extra', 'd+', '52'), ('bias', 'd+', '20'), ('call', '[A-Za-z_]w*', 'work'),
    ):
        trace = trace.replace(f'(?P<{key}>{generic})', value).replace(f'(?P={key})', value)
    rows = measured(trace, 9)
    source = '''
s32 f(s32 index) {
    s32 offset;
    offset = (s32) (index << 16) >> 14;
    work(M2C_FIELD(ctx, s32 *, 52) + (offset + 20));
    return M2C_FIELD((offset + M2C_FIELD(ctx, s32 *, 52)), s32 *, 20);
}
'''
    [(family, fixed)] = repair.variants(source, 'f', '', rows)
    assert family == 'inline_staged_address_sum'
    assert 'static inline s32 __repair_address_add' in fixed
    assert 'work(M2C_FIELD(ctx, s32 *, 52) + __repair_address_add(offset, 20));' in fixed
    assert not repair.variants(source.replace('offset + 20', 'offset + 24'), 'f', '', rows)


def test_normalization_requires_fast_math_and_keeps_reloads():
    rows = measured(repair._NORMALIZE_TARGET.replace('bc1fl @', 'bc1fl .Lstore'), 2)
    source = '''
f32 f(void *in, void *out) {
    f32 x; f32 y; f32 z; f32 length;
    x = M2C_FIELD(in, f32 *, 0);
    y = M2C_FIELD(in, f32 *, 4);
    z = M2C_FIELD(in, f32 *, 8);
    length = sqrtf((x * x) + (y * y) + (z * z));
    if (length == 0.0f) { length = 1.0f; }
    M2C_FIELD(out, f32 *, 0) = (f32) (x / length);
    M2C_FIELD(out, f32 *, 4) = (f32) (M2C_FIELD(in, f32 *, 4) / length);
    M2C_FIELD(out, f32 *, 8) = (f32) (M2C_FIELD(in, f32 *, 8) / length);
    return length;
}
'''
    [(family, fixed)] = repair.variants(source, 'f', '', rows, ('-ffast-math',))
    assert family == 'staged_float_normalization'
    assert 'f32 f(f32 *in, f32 *out)' in fixed
    assert '__builtin_sqrtf' in fixed
    assert 'out[1] = in[1]' in fixed and 'out[2] = in[2]' in fixed
    assert not repair.variants(source, 'f', '', rows)
    assert not repair.variants(source, 'f', '', rows, ('-ffast-math', '-fno-fast-math'))


def test_record_call_forwards_untouched_third_argument():
    trace = repair._FORWARD.pattern.replace(r'\n', '\n').replace('\\', '').replace('(?P<flag>d+)', '13').replace('(?P=flag)', '13')
    trace = trace.replace('(?P<call>[A-Za-z_]w*)', 'patch').replace('bnez $v0, @', 'bnez $v0, .Ldone')
    rows = measured(trace)
    source = '''
M2C_UNK patch(s32, s32, void *); /* extern */
void f(void *rec, s32 base) {
    s32 addr;
    if (M2C_FIELD(rec, u8 *, 13) == 0) {
        M2C_FIELD(rec, u8 *, 13) = 1U;
        M2C_FIELD(rec, s32 *, 0) = (s32) (M2C_FIELD(rec, s32 *, 0) + base);
        M2C_FIELD(rec, s32 *, 4) = (s32) (M2C_FIELD(rec, s32 *, 4) + base);
        addr = M2C_FIELD(rec, s32 *, 8) + base;
        M2C_FIELD(rec, s32 *, 8) = addr;
        patch(addr, base, rec);
    }
}
'''
    [(family, fixed)] = repair.variants(source, 'f', '', rows)
    assert family == 'forwarded_third_record_argument'
    assert 's32 __repair_address_forward)' in fixed
    assert 'patch(addr, base, __repair_address_forward)' in fixed
    assert not repair.variants(source, 'f', 'void f(void *, s32);', rows)


def test_repeated_member_byte_adds_follow_the_measured_operand_order():
    source = """typedef struct { float *points; } Points;
void f(Points *model) {
    s32 offset;
    offset = 0;
    use(offset + ((char *) model->points));
    use(offset + ((char *) model->points));
}
"""
    swapped = ('r', 'addu $v0, $a1, $v0', 'addu $v0, $v0, $a1')
    rows = [swapped, (' ', 'lwc1 $f0, ($v0)', 'lwc1 $f0, ($v0)'), swapped]
    assert repair.variants(source, 'f', '', rows, ['-mgp32']) == [
        ('measured_member_byte_add_order',
         source.replace('offset + ((char *) model->points)', '(u32)offset + (u32)model->points')),
    ]
    assert not repair.variants(source, 'f', '', rows, ['-mgp64'])
    assert not repair.variants(source, 'f', '', rows[:-1], ['-mgp32'])
    assert not repair.variants(source.replace('s32 offset;', 'volatile s32 offset;'), 'f', '', rows, ['-mgp32'])
