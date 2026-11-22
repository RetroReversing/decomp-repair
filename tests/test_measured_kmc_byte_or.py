from decomprepair.measured_kmc_byte_or import variants

SOURCE = '''void f(void *p) {
    u8 tmp;
    tmp = M2C_FIELD(p, u8 *, 2) | ~M2C_FIELD(p, u8 *, 1) | 0x90;
    M2C_FIELD(p, u8 *, 2) = tmp;
}'''
ROWS = [(' ', 'nor $v1, $zero, $v1', 'nor $v0, $zero, $v0'),
        (' ', 'or $v0, $v0, $v1', 'or $v1, $v1, $v0'),
        ('|', 'ori $v0, $v0, 0x90', 'addiu $v0, $zero, -0x70')]


def test_narrows_the_intermediate_or_for_the_byte_assignment():
    result = variants(SOURCE, 'f', '', ROWS)
    assert len(result) == 1
    assert '(u8)(M2C_FIELD(p, u8 *, 2) | ~M2C_FIELD(p, u8 *, 1)) | 0x90' in result[0][1]


def test_requires_measured_mask_and_narrow_destination():
    assert not variants(SOURCE, 'f', '', [])
    assert not variants(SOURCE.replace('u8 tmp;', 'u32 tmp;'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('0x90;', '0x91;'), 'f', '', ROWS)
    assert not variants(SOURCE, 'f', '', ROWS[:-1])


def test_does_not_narrow_a_shadowed_word_destination():
    source = SOURCE.replace('    tmp =', '    { int tmp; tmp =').replace('\n    M2C_FIELD(p, u8 *, 2) = tmp;', '\n    }')
    assert not variants(source, 'f', '', ROWS)
    assert not variants(SOURCE, 'f', '#define tmp other', ROWS)
