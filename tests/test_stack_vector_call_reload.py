from decomprepair.stack_vector_call_reload import variants

SOURCE = """
void delta(int index, float *out) {
    union {
        unsigned char bytes[32];
        struct { f32 value; } view_sp20;
        struct { unsigned char pad[4]; f32 value; } view_sp24;
        struct { unsigned char pad[8]; f32 value; } view_sp28;
    } m2c_initial_frame;
    sample(index, 1, &m2c_initial_frame.view_sp20.value);
    sample(index, 0, &m2c_initial_frame.view_sp20.value);
    M2C_FIELD(out, f32 *, 0) = (f32) (m2c_initial_frame.view_sp20.value - m2c_initial_frame.view_sp20.value);
    M2C_FIELD(out, f32 *, 4) = (f32) (m2c_initial_frame.view_sp24.value - m2c_initial_frame.view_sp24.value);
    M2C_FIELD(out, f32 *, 8) = (f32) (m2c_initial_frame.view_sp28.value - m2c_initial_frame.view_sp28.value);
}
"""


def assembly():
    lines = ['addiu $a2, $sp, 0x20', 'jal sample', 'nop', 'addiu $a2, $sp, 0x20']
    for i in range(3):
        lines.append(f'lwc1 $fs{i}, {0x20 + 4*i:#x}($sp)')
    lines += ['jal sample', 'nop']
    for i in range(3):
        lines += [f'lwc1 $f0, {0x20 + 4*i:#x}($sp)',
                  f'sub.s $fs{i}, $fs{i}, $f0', f'swc1 $fs{i}, {4*i:#x}($s0)']
    return '\n'.join(f'/* 0000 80000000 00000000 */ {line}' for line in lines)


def test_captures_only_when_target_uses_value_from_before_second_call():
    asm = assembly()
    [(family, result)] = variants(SOURCE, 'delta', asm)
    assert family == 'stack_vector_call_reload'
    assert result.index('sample(index, 1') < result.index('__repair_vector_before_0 =') < result.index('sample(index, 0')
    assert '__repair_vector_before_2 - m2c_initial_frame.view_sp28.value' in result
    assert 'bytes[32]' in result
    assert not variants(SOURCE, 'delta', asm.replace('sub.s $fs1, $fs1, $f0', 'sub.s $fs1, $f0, $fs1'))
    assert not variants(SOURCE.replace('sample(index, 0', 'other(index, 0'), 'delta', asm)
