"""A word read into a float local, retyped as the float the target loads with lwc1."""
from decomprepair import float_word_load_retype as r

SOURCE = '''void f(s32 src, s32 dst) {
    f32 *out;
    f32 t;
    u32 i;

    i = 0;
    do {
        out = dst + i * 4;
        t = *(s32 *)(src + i * 4);
        *out = t;
        i += 1;
    } while (i < 3U);
}
'''
ASM = 'lwc1       $fv0, 0x0($v0)\nswc1       $fv0, 0x0($v1)\n'


def test_the_integer_read_becomes_the_float_read():
    (out,) = [t for _, t in r.variants(SOURCE, 'f', ASM)]
    assert 't = *(f32 *)(src + i * 4);' in out and '*(s32 *)' not in out


def test_an_explicit_cast_and_field_macro_forms_are_covered():
    cast = SOURCE.replace('t = *(s32 *)(src + i * 4);', 't = (f32) *(u32 *)(src + i * 4);')
    assert 't = *(f32 *)(src + i * 4);' in r.variants(cast, 'f', ASM)[0][1]
    field = SOURCE.replace('t = *(s32 *)(src + i * 4);', 't = M2C_FIELD(src, s32 *, 0x10);')
    assert 't = M2C_FIELD(src, f32 *, 0x10);' in r.variants(field, 'f', ASM)[0][1]


def test_left_alone_when_the_target_converts_or_loads_no_float_or_the_target_is_an_int():
    assert r.variants(SOURCE, 'f', ASM + 'cvt.s.w    $f0, $f0\n') == []
    assert r.variants(SOURCE, 'f', 'lw         $v0, 0x0($v0)\n') == []
    assert r.variants(SOURCE.replace('f32 t;', 's32 t;'), 'f', ASM) == []


def test_it_declares_itself():
    assert r.REPAIR['families'] == ('float_word_load_retype',)
