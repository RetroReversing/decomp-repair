from decomprepair import global_array_repairs as arrays

TABLE = '''extern M2C_UNK D_801FAE30;

f32 f(s32 arg0) {
    return *(&D_801FAE30 + (((arg0 + 0x5A) & 0xFF) * 4));
}
'''


def test_scaled_word_access_becomes_a_typed_table_index():
    out = [t for family, t in arrays.variants(TABLE, 'f') if family == 'global_table_index']
    assert len(out) == 3 and 'extern f32 D_801FAE30[];' in out[0]
    assert 'return D_801FAE30[((arg0 + 0x5A) & 0xFF)];' in out[0]


def test_table_with_another_kind_of_use_is_left_alone():
    def indexed(text):
        return [1 for family, _ in arrays.variants(text, 'f') if family == 'global_table_index']
    assert not indexed(TABLE.replace('return', 'g(D_801FAE30); return'))
    assert not indexed(TABLE.replace('* 4)', '* 8)'))


def test_byte_table_signedness_is_flipped():
    source = 'extern char D_8011F2FC[];\nint f(int i) { return D_8011F2FC[i]; }\n'
    assert [t for fam, t in arrays.variants(source, 'f') if fam == 'byte_table_signedness'] == [source.replace('char', 'u8'), source.replace('char', 's8')]


def test_address_only_global_becomes_a_byte_table():
    source = 'extern M2C_UNK D_8011F2F0;\nvoid *f(s32 a) { return ((a & 0xFFFF) * 0x64) + &D_8011F2F0; }\n'
    out = [t for fam, t in arrays.variants(source, 'f') if fam == 'global_address_table']
    assert out[0] == 'extern u8 D_8011F2F0[];\nvoid *f(s32 a) { return ((a & 0xFFFF) * 0x64) + D_8011F2F0; }\n'
    assert not [1 for fam, _ in arrays.variants(source.replace('+ &D', '+ D'), 'f') if fam == 'global_address_table']


def test_scalar_global_tries_other_widths_and_signedness():
    source = 'extern s32 D_41CF00;\nvoid f(void) { D_41CF00 = 1; }\n'
    out = [t for fam, t in arrays.variants(source, 'f') if fam == 'global_scalar_type']
    assert source.replace('s32', 's8') in out and source.replace('s32', 'u32') in out
    assert not arrays.variants('extern s32 D_41CF00;\nvoid f(void) { }\n', 'f')


def test_scalar_globals_of_one_type_are_also_changed_together():
    source = 'extern s32 D_41CF00;\nextern s32 D_425610;\nvoid f(void) { D_41CF00 = D_425610; }\n'
    out = [t for fam, t in arrays.variants(source, 'f') if fam == 'global_scalar_type']
    assert source.replace('s32', 's8') in out


def test_byte_table_read_is_tried_as_a_halfword():
    source = ('extern char D_8011F32E[];\nu16 f(s32 a, s32 b) {\n'
              '    return (*(D_8011F32E + ((a & 0xFFFF) * 0x64)) & 0xFFF) | (b * (D_8011F32E + 4));\n}\n')
    out = [t for fam, t in arrays.variants(source, 'f') if fam == 'table_read_width']
    assert out[0] == source.replace('*(D_8011F32E + ((a', '*(u16 *)(D_8011F32E + ((a')
    assert len(out) == 2  # the product `b * (T + 4)` is not a dereference: one site, u16 then s16


def test_every_byte_table_read_is_widened_at_once_first():
    source = ('extern char D_8011F2F4[];\nextern char D_8011F2F8[];\n'
              'void f(s32 t) {\n    *(D_8011F2F4 + t) = *(D_8011F2F4 + t) | 0x20;\n    *(D_8011F2F8 + t) = *(D_8011F2F8 + t) | 0x20;\n}\n')
    first = [t for fam, t in arrays.variants(source, 'f') if fam == 'table_read_width'][0]
    assert first.count('*(u16 *)(') == 4


def test_scalar_call_argument_can_be_the_first_array_element():
    source = 'extern s32 table;\nvoid f(void) { call(0, table, 1); }\n'
    variants = [text for family, text in arrays.variants(source, 'f') if family == 'global_first_element']
    assert variants == ['extern s32 table[];\nvoid f(void) { call(0, table[0], 1); }\n']


def test_first_element_leaves_other_uses_alone():
    source = 'extern s32 table;\nvoid f(void) { call(0, table, 1); }\n'
    for text in (source + 'int g(void) { return table; }\n',
                 source.replace('table, 1', '&table, 1'),
                 source.replace('call(0, table, 1);', 'table = 1;')):
        assert not [text for family, text in arrays.variants(text, 'f') if family == 'global_first_element']


FLAG = ('extern u8 flag;\nvoid f(P *p) {\n    p->a->mode = 1;\n    if (flag) { p->b = 2; }\n'
        '    if (flag) { p->c = 3; }\n}\n')


def _reads(source):
    return [text for family, text in arrays.variants(source, 'f') if family == 'global_first_element']


def test_every_scalar_flag_read_becomes_element_zero_together():
    expected = FLAG.replace('flag;', 'flag[];').replace('(flag)', '(flag[0])')
    assert expected in _reads(FLAG)


def test_volatile_cast_flag_read_becomes_the_plain_element():
    source = FLAG.replace('if (flag) { p->c', 'if (*(volatile u8 *)&flag) { p->c')
    expected = FLAG.replace('flag;', 'flag[];').replace('(flag)', '(flag[0])')
    assert expected in _reads(source)


def test_flag_first_element_leaves_written_or_addressed_flags_alone():
    for text in (FLAG.replace('p->b = 2;', 'flag = 2;'), FLAG.replace('p->b = 2;', 'q(&flag);'),
                 FLAG.replace('p->b = 2;', 'flag++;'), FLAG.replace('p->b = 2;', '++flag;'),
                 FLAG + 'int g(void) { return flag; }\n'):
        assert not _reads(text)
