from decomprepair.halved_halfword_one_word import FAMILY, variants

SOURCE = '''void f(u16 *p) {
    u32 t2;
    u16 t;
    u16 v;
    s32 a;
    a = p[0] + 1;
    {
        t2 = (u32) (a << 0x10) >> 0x1F;
        t = (u16) ((s32) ((s16) a + t2) >> 1);
        v = t;
        p[1] = v;
    }
}
'''


def children(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_sign_bit_and_value_come_from_one_shifted_word():
    plain, folded = children()
    assert 't = (u16) (h >> 1); }' in plain
    assert 'u32 w = (u32) (a << 0x10); s32 h = (s32) w >> 16; h += w >> 31;' in plain
    assert 't2 = ' not in plain
    assert 'v = (u16) (h >> 1); }' in folded and 'v = t;' not in folded


def test_inline_sign_bit_in_either_order():
    src = '''void f(s32 a, u16 *p) {
    p[0] = 0;
    v = (u16) ((s32) ((s16) a + ((u32) (a << 16) >> 31)) >> 1);
}
'''
    (child,) = children(src)
    assert 'v = (u16) (h >> 1); }' in child
    swapped = src.replace('(s16) a + ((u32) (a << 16) >> 31)', '((u32) (a << 16) >> 31) + (s16) a')
    assert len(children(swapped)) == 1


def test_other_operands_or_a_shared_sign_local_are_left_alone():
    assert not children(SOURCE.replace('(s16) a +', '(s16) b +'))
    assert not children(SOURCE.replace('>> 0x1F', '>> 0x1E'))
    assert not children(SOURCE.replace('v = t;', 'v = t + t2;'))
