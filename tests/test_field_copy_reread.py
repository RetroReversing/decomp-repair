from decomprepair import field_copy_reread as repairs

SOURCE = '''void f(void *p) {
    s32 a0;
    s32 a1;
    s32 v0;
    s32 masked;
    u16 v1;

    a0 = (*(s32 *)((s8 *)p + 0x34)); (*(s32 *)((s8 *)p + 0x34)) = a0 + (*(s32 *)((s8 *)p + 0x40));
    v0 = (*(s32 *)((s8 *)p + 0x34));
    a1 = (*(s32 *)((s8 *)p + 0x44));
    a0 = (*(s32 *)((s8 *)p + 0x38));
    do { v1 = (*(u16 *)((s8 *)p + 0x3A)) + (v0 >> 2); } while (0);
    do { (*(u16 *)((s8 *)p + 0x6A)) = v1; } while (0);
    masked = v1 & 0xFFFF;
    if (a0 < masked) {
        v0 = f3(p, a1);
        (*(s32 *)((s8 *)p + 0x3C)) = v0;
        return;
    }
    if (masked < a0) {
        (*(s32 *)((s8 *)p + 0x40)) = 1;
    }
}
'''


def children():
    return repairs.variants(SOURCE, 'f')


def test_every_copy_is_written_as_its_field_in_one_child():
    family, text = children()[0]
    assert family == repairs.ARITY_FAMILY
    assert ' a0' not in text.split('u16 v1;')[1] and 'masked <' not in text and '< masked' not in text
    assert 'f3(p);' in text  # the register m2c passed along is not an argument
    assert 'if ((*(u16 *)((s8 *)p + 0x6A)) < (*(s32 *)((s8 *)p + 0x38)))' in text  # the masked copy too
    assert 'do {' not in text
    assert '((*(s32 *)((s8 *)p + 0x34)) >> 2)' in text


def test_the_argument_is_kept_in_the_plain_child():
    text = next(text for family, text in children() if family == repairs.FAMILY)
    assert 'f3(p, (*(s32 *)((s8 *)p + 0x44)))' in text


def test_a_read_after_a_call_keeps_its_local():
    source = '''void f(u8 *p) {
    s32 a;
    a = (*(s32 *)((u8 *)p + 4));
    g();
    h(a);
}
'''
    assert repairs.variants(source, 'f') == []


def test_a_store_to_the_same_field_keeps_the_local():
    source = '''void f(u8 *p) {
    s32 a;
    a = (*(s32 *)((u8 *)p + 4));
    (*(s32 *)((u8 *)p + 4)) = 0;
    (*(s32 *)((u8 *)p + 8)) = a;
}
'''
    assert repairs.variants(source, 'f') == []


def test_a_member_copy_is_read_again_past_another_member():
    source = '''void f(T *p) {
    s32 a;
    a = p->height;
    p->speed = 1;
    p->y = a;
}
'''
    [(_, text)] = repairs.variants(source, 'f')
    assert 'p->y = (p->height);' in text and 'a = p->height' not in text


def test_a_mask_of_a_value_stored_through_a_copy_is_read_back():
    source = SOURCE.replace('do { (*(u16 *)((s8 *)p + 0x6A)) = v1; } while (0);',
                            'do { copy = v1; (*(u16 *)((s8 *)p + 0x6A)) = copy; } while (0);')
    source = source.replace('    u16 v1;\n', '    u16 v1;\n    s32 copy;\n')
    text = repairs.variants(source, 'f')[0][1]
    assert 'masked =' not in text
