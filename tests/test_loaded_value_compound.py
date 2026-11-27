"""A value loaded only to update where it came from, written as a compound assignment (made-up names)."""
from decomprepair import loaded_value_compound as repair

SOURCE = '''void f(s8 *obj) {
    f32 temp;
    f32 temp_2;
    f32 result;
    temp = M2C_FIELD(obj, f32 *, 0x34);
    M2C_FIELD(obj, f32 *, 0x34) = (f32) (((3.0f - temp) * 0.4f) + temp);
    temp_2 = M2C_FIELD(obj, f32 *, 0x30);
    result = ((0.3f - temp_2) * 0.4f) + temp_2;
    M2C_FIELD(obj, f32 *, 0x30) = result;
    if (result > 2.8f) {
        return;
    }
}
'''


def test_every_site_together_comes_first():
    family, text = repair.variants(SOURCE, 'f')[0]
    assert family == 'loaded_value_compound'
    assert 'M2C_FIELD(obj, f32 *, 0x34) += ((3.0f - M2C_FIELD(obj, f32 *, 0x34)) * 0.4f);' in text
    assert 'M2C_FIELD(obj, f32 *, 0x30) += ((0.3f - M2C_FIELD(obj, f32 *, 0x30)) * 0.4f);' in text
    assert 'if (M2C_FIELD(obj, f32 *, 0x30) > 2.8f)' in text
    assert 'temp = ' not in text and 'result = ' not in text


def test_each_site_alone():
    assert len(repair.variants(SOURCE, 'f')) == 3


def test_global_and_subtraction():
    source = 'extern s32 gTotal;\nvoid f(void) {\n    s32 t;\n    t = gTotal;\n    gTotal = t - (t >> 4);\n}\n'
    assert 'gTotal -= (gTotal >> 4);' in repair.variants(source, 'f')[0][1]


def test_left_alone_when_the_local_is_needed_or_narrower():
    used_again = SOURCE.replace('        return;\n', '        g(temp, temp_2, result);\n')
    assert repair.variants(used_again, 'f') == []
    narrow = 'void f(s8 *p) {\n    u8 t;\n    t = M2C_FIELD(p, s32 *, 4);\n    M2C_FIELD(p, s32 *, 4) = (t >> 1) + t;\n}\n'
    assert repair.variants(narrow, 'f') == []
    called = 'void f(s8 *p) {\n    s32 t;\n    t = M2C_FIELD(p, s32 *, 4);\n    M2C_FIELD(p, s32 *, 4) = (g() * t) + t;\n}\n'
    assert repair.variants(called, 'f') == []
