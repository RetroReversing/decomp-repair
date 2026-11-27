from decomprepair import address_global_pointer, discarded_result_void, returned_gfx_cursor

SOURCE = '''M2C_UNK g(M2C_UNK *, s32, void *); /* extern */
s32 h(); /* extern */
extern s32 D_80090000;
extern s32 D_80070000;

s32 f(void *arg0, s32 arg1) {
    s32 temp_a1;

    M2C_FIELD(arg0, s32 *, 0) = 0xDA380001;
    temp_a1 = D_80090000 + ((D_80070000 << 6) + 0xB8);
    M2C_FIELD(arg0, s32 *, 4) = (s32) (temp_a1 + 0x80000000);
    g(&D_80070000, temp_a1, arg0);
    arg1 = h();
    D_80070000 += 1;
    return arg0 + 8;
}
'''


def test_discarded_result_is_declared_void_only_when_never_read():
    children = discarded_result_void.variants(SOURCE, 'f')
    assert [family for family, _ in children] == ['discarded_result_void']
    assert 'void g(M2C_UNK *, s32, void *);' in children[0][1]
    assert 's32 h(); /* extern */' in children[0][1]
    assert discarded_result_void.variants(SOURCE, 'f', 'int g(int);') == []


def test_guarded_call_statement_counts_and_a_nested_call_does_not():
    source = 's32 g(s32);\nvoid f(s32 a) {\n    if (a) g(a);\n}\n'
    assert 'void g(s32);' in discarded_result_void.variants(source, 'f')[0][1]
    assert discarded_result_void.variants(source.replace('if (a) g(a);', 'k(g(a));'), 'f') == []


def test_address_only_global_becomes_a_pointer():
    children = address_global_pointer.variants(SOURCE, 'f')
    assert len(children) == 1
    assert 'extern u8 *D_80090000;' in children[0][1]
    assert 'extern s32 D_80070000;' in children[0][1]


def test_returned_cursor_becomes_the_macro_and_drops_the_stray_argument():
    children = returned_gfx_cursor.variants(SOURCE, 'f')
    assert len(children) == 1
    text = children[0][1]
    assert 'M2C_UNK g(M2C_UNK *, s32); /* extern */' in text
    assert 'g(&D_80070000, temp_a1);' in text
    assert '''    {
        RepairGfxWords *_g = (RepairGfxWords *)arg0;
        arg0 = (void *)((char *)arg0 + 8);
        _g->w0 = 0xDA380001;
        temp_a1 = D_80090000 + ((D_80070000 << 6) + 0xB8);
        _g->w1 = (unsigned int)((s32) (temp_a1 + 0x80000000));
    }
''' in text
    assert 'return arg0;' in text
    assert text.index('RepairGfxWords;') < text.index('s32 f(')


def test_two_commands_and_other_uses():
    source = '''void *f(void *p) {
    M2C_FIELD(p, s32 *, 0) = 1;
    M2C_FIELD(p, s32 *, 4) = 2;
    M2C_FIELD(p, s32 *, 8) = 3;
    M2C_FIELD(p, s32 *, 0xC) = 4;
    return p + 0x10;
}
'''
    assert returned_gfx_cursor.variants(source, 'f')[0][1].count('RepairGfxWords *_g') == 2
    assert returned_gfx_cursor.variants(source.replace('0x10;', '8;'), 'f') == []
    assert returned_gfx_cursor.variants(source.replace('return', 'q(p->x);\n    return'), 'f') == []


CHAINED = '''s32 g(s32);
extern s16 D_80070000;

s32 f(void *arg0, s32 arg1) {
    void *temp_s0;
    void *temp_s0_2;

    temp_s0 = arg0 + 8;
    temp_s0_2 = temp_s0 + 8;
    M2C_FIELD(arg0, s32 *, 0) = 0xE7000000;
    M2C_FIELD(arg0, s32 *, 4) = 0;
    M2C_FIELD(arg0, s32 *, 8) = 0xFE000000;
    M2C_FIELD(temp_s0, s32 *, 4) = g(arg1);
    M2C_FIELD(temp_s0_2, s32 *, 4) = 0x300000;
    M2C_FIELD(temp_s0, s32 *, 8) = (s32) (((D_80070000 - 1) & 0xFFF) | 0xFF100000);
    return temp_s0_2 + 8;
}
'''


def test_derived_command_pointers_become_offsets_in_address_order():
    children = returned_gfx_cursor.variants(CHAINED, 'f')
    assert len(children) == 1
    text = children[0][1]
    assert 'temp_s0' not in text
    assert text.count('RepairGfxWords *_g') == 3
    assert text.index('0xFF100000') < text.index('0x300000')
    assert 'return arg0;' in text


def test_derived_pointers_used_another_way_or_reordered_calls_are_left_alone():
    assert returned_gfx_cursor.variants(CHAINED.replace('return', 'g(temp_s0->x);\n    return'), 'f') == []
    # a value naming a global would move to the other side of the call
    moved = CHAINED.replace('M2C_FIELD(temp_s0_2, s32 *, 4) = 0x300000;', 'M2C_FIELD(temp_s0_2, s32 *, 4) = g(2);')
    moved = moved.replace('M2C_FIELD(temp_s0, s32 *, 8) = (s32)', 'M2C_FIELD(temp_s0, s32 *, 8) = (s32)', 1)
    assert returned_gfx_cursor.variants(moved, 'f') == []
