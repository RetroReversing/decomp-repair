"""A triangle's vertices built in the arms of a halfword-or-byte index test, each arm calling.

Synthetic shape of the 851-instruction ray test: m2c's three temporaries per arm and the shared call after the
`if`/`else`, and the shape an earlier search left (the call repeated in each arm)."""
from decomprepair import triangle_arm_calls as t

SHARED = '''void plane(void *obj, s32 i, void *out)
{
    s32 var_a1;
    s32 var_a2;
    u16 var_v0;
    void *temp_v1;
    void *temp_v2;
    if (M2C_FIELD(obj, u8 *, 0x48) & 4) {
        temp_v1 = M2C_FIELD(obj, u8 **, 0x3C) + (i * 6);
        var_a1 = M2C_FIELD(obj, s32 *, 0x34) + (M2C_FIELD(temp_v1, u16 *, 0) * 0xC);
        var_a2 = M2C_FIELD(temp_v1, u16 *, 2) * 3;
        var_v0 = M2C_FIELD(temp_v1, u16 *, 4);
    } else {
        temp_v2 = M2C_FIELD(obj, u8 **, 0x3C) + (i * 3);
        var_a1 = M2C_FIELD(obj, s32 *, 0x34) + (M2C_FIELD(temp_v2, u8 *, 0) * 0xC);
        var_a2 = M2C_FIELD(temp_v2, u8 *, 1) * 3;
        var_v0 = (u16) M2C_FIELD(temp_v2, u8 *, 2);
    }
    build(out, var_a1, M2C_FIELD(obj, s32 *, 0x34) + (var_a2 * 4), M2C_FIELD(obj, s32 *, 0x34) + (var_v0 * 0xC));
}
'''
IN_ARMS = SHARED.replace('''    }
    build(out, var_a1, M2C_FIELD(obj, s32 *, 0x34) + (var_a2 * 4), M2C_FIELD(obj, s32 *, 0x34) + (var_v0 * 0xC));
''', '''    }
''').replace('''        var_v0 = M2C_FIELD(temp_v1, u16 *, 4);
''', '''        var_v0 = M2C_FIELD(temp_v1, u16 *, 4);
        build(out, var_a1, M2C_FIELD(obj, s32 *, 0x34) + (var_a2 * 4), M2C_FIELD(obj, s32 *, 0x34) + (var_v0 * 0xC));
''').replace('''        var_v0 = (u16) M2C_FIELD(temp_v2, u8 *, 2);
''', '''        var_v0 = (u16) M2C_FIELD(temp_v2, u8 *, 2);
        build(out, var_a1, M2C_FIELD(obj, s32 *, 0x34) + (var_a2 * 4), M2C_FIELD(obj, s32 *, 0x34) + (var_v0 * 0xC));
''')


def _texts(source):
    found = t.variants(source, 'plane')
    assert all(family == t.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_shared_call_becomes_a_call_in_each_arm():
    [text] = _texts(SHARED)
    assert 'u16 *tri = (u16 *)M2C_FIELD(obj, u8 **, 0x3C) + i * 3;' in text
    assert 'u8 *tri = (u8 *)M2C_FIELD(obj, u8 **, 0x3C) + i * 3;' in text
    call = 'build(out, (s32)(M2C_FIELD(obj, f32 **, 0x34) + tri[0] * 3), (s32)(M2C_FIELD(obj, f32 **, 0x34) + tri[1] * 3), (s32)(M2C_FIELD(obj, f32 **, 0x34) + tri[2] * 3));'
    assert text.count(call) == 2
    assert 'var_a1 =' not in text


def test_a_call_repeated_in_each_arm_gives_the_same_arms():
    [text] = _texts(IN_ARMS)
    assert text.count('(s32)(M2C_FIELD(obj, f32 **, 0x34) + tri[2] * 3)') == 2


def test_the_arms_are_rewritten_together_and_each_alone():
    two = SHARED.replace('}\n', '}\n', 1)
    body = SHARED[SHARED.index('    if ('):SHARED.rindex('}')]
    doubled = SHARED.replace(body, body + body)
    texts = _texts(doubled)
    assert len(texts) == 3
    assert texts[0].count('u16 *tri =') == 2 and texts[1].count('u16 *tri =') == 1 and two


def test_a_call_with_other_arguments_is_left_alone():
    other = SHARED.replace('(var_a2 * 4)', '(var_a2 * 8)')
    assert _texts(other) == []


def test_arms_that_read_another_triple_are_left_alone():
    other = SHARED.replace('M2C_FIELD(temp_v2, u8 *, 1) * 3', 'M2C_FIELD(temp_v1, u8 *, 1) * 3')
    assert _texts(other) == []


def test_an_inline_triple_address_is_read_as_the_temporary_is():
    inline = SHARED.replace('        temp_v1 = M2C_FIELD(obj, u8 **, 0x3C) + (i * 6);\n', '').replace('temp_v1', '(M2C_FIELD(obj, u8 **, 0x3C) + (i * 6))')
    inline = inline.replace('        temp_v2 = M2C_FIELD(obj, u8 **, 0x3C) + (i * 3);\n', '').replace('temp_v2', '(M2C_FIELD(obj, u8 **, 0x3C) + (i * 3))')
    [text] = _texts(inline)
    assert 'u16 *tri = (u16 *)M2C_FIELD(obj, u8 **, 0x3C) + i * 3;' in text
