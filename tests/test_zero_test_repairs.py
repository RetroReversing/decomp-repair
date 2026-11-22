from decomprepair import zero_test_repairs as repairs


def test_pointer_zero_identity_keeps_a_defined_pointer_through_the_initializer():
    source = 'void f(void) { char *p = global; s32 done = 0; use(done); }\n'
    out = repairs.pointer_zero_identity(source, 'f', 'mips', 'typedef unsigned u32;')
    assert out == [('kmc_pointer_zero_identity', source.replace('done = 0', 'done = (u32)p & ~(u32)p'))]
    assert not repairs.pointer_zero_identity(source, 'f', 'x86', 'typedef unsigned u32;')
    assert not repairs.pointer_zero_identity(source.replace('p = global', 'p'), 'f', 'mips', 'typedef unsigned u32;')
