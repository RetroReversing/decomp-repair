"""Prototypes from call sites, and m2c's dropped `!= 0` in a masked flag test."""
from decomprepair import call_site_prototype_repairs as c
from decomprepair import masked_flag_test_repairs as m

PROTO = '''f32 sinf_();
void *draw();
s32 h();

void f(f32 a, s32 *p) {
    f32 t;

    t = a * 2.0f;
    draw(p, 0, sinf_(t), 1.0f);
    h(p, 3);
}
'''


def test_callees_with_float_arguments_get_prototypes():
    # An N64 function: its sin/cos and draw calls passed doubles where the game passed floats; 77% -> 98% with these.
    (family, out), = c.variants(PROTO, 'f')
    assert family == 'call_site_prototype'
    assert 'f32 sinf_(f32);' in out and 'void *draw(s32, s32, f32, f32);' in out
    assert 's32 h();' in out  # integer arguments only: left as m2c declared it


def test_prototypes_left_alone_when_calls_disagree():
    two = PROTO.replace("    h(p, 3);\n", "    h(p, 3);\n    draw(p);\n")
    out = c.variants(two, 'f')
    assert not out or 'void *draw();' in out[0][1]


FLAG = '''void f(void *arg0, void *arg1) {
    if (M2C_FIELD(arg0, s32 *, 0x60) & 0xC00 & (arg1 != NULL)) {
        g();
    }
}
'''


def test_the_dropped_comparison_is_put_back():
    # As m2c wrote it the test is always 0 and gcc deleted the block: 51 of 251 instructions; 18.9% -> 50.2%.
    (family, out), = m.variants(FLAG, 'f')
    assert family == 'masked_flag_test'
    assert 'if (((M2C_FIELD(arg0, s32 *, 0x60) & 0xC00) != 0) & (arg1 != NULL)) {' in out


def test_an_odd_mask_is_left_alone():
    assert m.variants(FLAG.replace('0xC00', '0xC01'), 'f') == []
