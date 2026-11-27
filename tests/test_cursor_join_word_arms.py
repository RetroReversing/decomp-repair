from decomprepair import cursor_join_word_arms as repair

SOURCE = '''void f(void **gfx, s32 mode) {
    u8 *v;
    void *t;
    void *u;
    if (mode == 0) {
        t = *gfx;
        *gfx = t + 8;
        *(s32 *)t = 0x06000000;
        v = &D_a;
    } else {
        u = *gfx;
        *gfx = u + 8;
        *(s32 *)u = 0x06000000;
        v = &D_b;
    }
    *(u8 **)((u8 *)(*gfx) + 4) = v;
}
'''


def test_the_joined_word_goes_into_each_arm_through_its_pointer():
    [(family, child)] = repair.variants(SOURCE, 'f')
    assert family == repair.FAMILY
    assert '*(u8 **)((u8 *)t + 4) = &D_a;' in child
    assert '*(u8 **)((u8 *)u + 4) = &D_b;' in child
    assert '(*gfx) + 4' not in child


def test_a_value_read_elsewhere_stays():
    assert repair.variants(SOURCE.replace('    *(u8 **)', '    use(v);\n    *(u8 **)'), 'f') == []


def test_an_arm_that_took_no_command_stays():
    assert repair.variants(SOURCE.replace('        t = *gfx;\n        *gfx = t + 8;\n', ''), 'f') == []
