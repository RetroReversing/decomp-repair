from decomprepair.float_stack_call_reuse import FAMILY, variants

SOURCE = '''inline static const f32 read_float(const f32 *p, int offset) {
    return *((const f32 *) (((char *) p) + offset));
}
float f(const f32 *p) {
    volatile f32 x;
    volatile f32 y;
    volatile f32 z;
    f32 out;
    x = read_float(p, 0);
    y = read_float(p, 4);
    z = read_float(p, 8);
    out = angle(y, hypot(p[0], p[2]));
    return out + x + z;
}'''
ASM = '''lwc1 $fa0, 0($s0)
swc1 $fa0, 0x10($sp)
lwc1 $fv0, 4($s0)
swc1 $fv0, 0x14($sp)
lwc1 $fa1, 8($s0)
jal another_symbol_name
swc1 $fa1, 0x18($sp)
'''


def test_reuses_copies_as_call_arguments_without_reloading_the_stack():
    [(family, text)] = variants(SOURCE, 'f', 'mips', ASM)
    assert family == FAMILY
    assert 'x = __repair_float_x = read_float(p, 0);' in text
    assert 'z = __repair_float_z = read_float(p, 8);' in text
    assert '__repair_float_call = hypot(__repair_float_x, __repair_float_z);' in text
    assert 'out = angle(y, __repair_float_call);' in text


def test_requires_checked_loads_and_float_argument_registers():
    assert not variants(SOURCE.replace('p[2]', 'p[1]'), 'f', 'mips', ASM)
    assert not variants(SOURCE.replace('volatile f32 z', 'f32 z'), 'f', 'mips', ASM)
    assert not variants(SOURCE.replace(' return *((const', ' mutate(p); return *((const'), 'f', 'mips', ASM)
    assert not variants(SOURCE, 'f', 'mips', ASM.replace('lwc1 $fa1', 'lwc1 $fv0'))
