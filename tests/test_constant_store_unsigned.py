from decomprepair.constant_store_unsigned import variants

BYTE = 'addiu $v1, $zero, 0xc8\nsb $v1, 0x17($v0)\n'
HALF = 'ori $v1, $zero, 0xc800\nsh $v1, 0x2($a0)\n'


def test_an_m2c_byte_field_store_above_0x7f_becomes_u8():
    source = 'void f(void *a) {\n    void *temp_v0 = a;\n    M2C_FIELD(temp_v0, s8 *, 0x17) = 0xC8;\n}\n'
    assert variants(source, 'f', BYTE) == [('constant_store_unsigned', source.replace('s8 *', 'u8 *'))]


def test_every_byte_constant_from_0x80_to_0xff_is_covered():
    for value in (0x80, 0x81, 0xC8, 0xFE, 0xFF):
        source = f'void f(void *p) {{\n    M2C_FIELD(p, s8 *, 4) = {value};\n}}\n'
        asm = f'li $v1, {value:#x}\n'
        assert 'u8 *' in variants(source, 'f', asm)[0][1], value


def test_a_halfword_above_0x7fff_becomes_u16_and_decimal_is_read():
    source = 'void f(void *p) {\n    M2C_FIELD(p, s16 *, 2) = 51200;\n    *(s16 *)((char *)p + 6) = 0xC800;\n}\n'
    found = variants(source, 'f', HALF)
    assert found[0][1].count('u16 *') == 2 and 's16' not in found[0][1]
    assert len(found) == 3  # all, then each


def test_a_cast_store_and_a_member_become_unsigned():
    source = ('typedef struct { s8 a, b; s16 c; } R;\nvoid f(R *p, char *q) {\n    p->a = 0xC8;\n    p->c = 0xC8;\n'
              '    *(s8 *)(q + 1) = 0xC8;\n}\n')
    first = variants(source, 'f', BYTE)[0][1]
    assert 'typedef struct { u8 a; s8 b; s16 c; } R;' in first and '*(u8 *)(q + 1)' in first


def test_nothing_without_the_unsigned_constant_in_the_target_or_when_the_value_fits_a_signed_field():
    source = 'void f(void *p) {\n    M2C_FIELD(p, s8 *, 4) = 0xC8;\n}\n'
    assert variants(source, 'f', 'addiu $v1, $zero, -0x38\n') == []
    assert variants(source, 'f', '') == []
    assert variants('void f(void *p) {\n    M2C_FIELD(p, s8 *, 4) = 0x40;\n}\n', 'f', 'li $v1, 0x40\n') == []
    assert variants('void f(void *p) {\n    M2C_FIELD(p, s8 *, 4) = 0x1C8;\n}\n', 'f', 'li $v1, 0x1c8\n') == []
