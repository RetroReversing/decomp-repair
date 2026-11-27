from decomprepair import clamp_call_arms

SOURCE = '''typedef struct { u8 alpha; } Obj;
void draw(Gfx **gfxp, u16 id) {
    u32 a;

    begin(gfxp);
    a = D_obj[id].alpha;
    if (a >= 0xAA) {
        a = 0x64;
    }
    set_alpha(gfxp, a);
    end(gfxp);
}
'''

ARMS = '''    if (D_obj[id].alpha < 0xAA) {
        set_alpha(gfxp, D_obj[id].alpha);
    } else {
        set_alpha(gfxp, 0x64);
    }
    end(gfxp);'''


def test_the_clamped_argument_becomes_a_call_in_each_arm():
    children = clamp_call_arms.variants(SOURCE, 'draw')
    assert [family for family, _ in children] == ['clamp_call_arms'] * 2
    assert ARMS in children[0][1]
    assert 'if (D_obj[id].alpha >= 0xAA) {\n        set_alpha(gfxp, 0x64);' in children[1][1]


def test_an_unbraced_clamp_is_read_too():
    source = SOURCE.replace('if (a >= 0xAA) {\n        a = 0x64;\n    }', 'if (a >= 0xAA)\n        a = 0x64;')
    assert ARMS in clamp_call_arms.variants(source, 'draw')[0][1]


def test_a_local_read_again_is_left_alone():
    assert clamp_call_arms.variants(SOURCE.replace('end(gfxp);', 'end(a);'), 'draw') == []


def test_a_value_from_a_call_is_left_alone():
    assert clamp_call_arms.variants(SOURCE.replace('D_obj[id].alpha;', 'get(id);'), 'draw') == []
