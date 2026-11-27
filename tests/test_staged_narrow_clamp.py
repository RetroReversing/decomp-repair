from decomprepair import staged_narrow_clamp as repair

TWO_LOCALS = """void f(void *o) {
    s32 t;
    s8 v;

    t = (*((u8 *) (((char *) o) + 0x72))) - 1;
    v = t;
    if (t < 0x41) {
        v = 0x40;
    }
    *((s8 *) (((char *) o) + 0x71)) = v;
}
"""

ONE_LOCAL = """typedef struct { u8 g; } Obj;
void f(Obj *o) {
    s32 v;

    v = o->g - 1;
    if (v < 0x41) v = 0x40;
    o->g = v;
}
"""


def test_two_locals_become_a_staged_narrow_clamp():
    children = [child for _, child in repair.variants(TWO_LOCALS, 'f')]
    assert len(children) == 2
    assert 'u16 t;\n    s16 v;' in children[0]
    assert 's16 t;\n    s16 v;' in children[1]
    assert ('v = (*((u8 *) (((char *) o) + 0x72)));\n    t = v - 1;\n    v = t;\n'
            '    if (v < 0x41) { v = 0x40; }') in children[0]


def test_one_local_gets_a_stage_of_its_own():
    children = [child for _, child in repair.variants(ONE_LOCAL, 'f')]
    assert len(children) == 2
    assert 's16 v; u16 repair_prior;' in children[0]
    assert 'v = o->g;\n    repair_prior = v - 1;\n    v = repair_prior;' in children[0]


def test_a_word_load_is_left_alone():
    assert repair.variants(ONE_LOCAL.replace('u8 g', 's32 g'), 'f') == []
