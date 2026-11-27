from decomprepair import dividend_in_place as repair

DRAFT = '''void f(void *arg0) {
    s32 other;

    M2C_FIELD(arg0, s32 *, 0x34) = 0xF0;
    M2C_FIELD(arg0, u16 *, 0x6A) = (M2C_FIELD(arg0, u16 *, 0x6A) - ((M2C_FIELD(arg0, u16 *, 0x6A) - M2C_FIELD(arg0, s32 *, 0x38)) % 5)) + 5;
}
'''


def sources(text, name='f'):
    return [child for _, child in repair.variants(text, name)]


def test_names_the_dividend_before_the_statement_and_above_the_constant_store():
    here, above = sources(DRAFT)
    split = ('repair_dividend = M2C_FIELD(arg0, u16 *, 0x6A) - M2C_FIELD(arg0, s32 *, 0x38);\n'
             '    repair_dividend %= 5;\n')
    for child in (here, above):
        assert 's32 repair_dividend;' in child and split in child and '- (repair_dividend)) + 5;' in child
    assert here.index('= 0xF0;') < here.index('repair_dividend =')
    assert above.index('repair_dividend =') < above.index('= 0xF0;')


def test_stays_below_a_store_the_dividend_reads():
    assert len(sources(DRAFT.replace('0x34) = 0xF0', '0x38) = 0xF0'))) == 1


def test_splits_a_remainder_already_in_a_local():
    text = 'void f(Obj *p) {\n    s32 rem;\n    rem = (p->angle - p->target) % 5;\n    p->angle -= rem;\n}\n'
    assert sources(text) == [text.replace('rem = (p->angle - p->target) % 5;',
                                          'rem = p->angle - p->target;\n    rem %= 5;')]


def test_quotient_and_unsigned_operand():
    text = 'void f(u32 a, s32 *out) {\n    *out = (a + 3) / 10;\n}\n'
    assert 'u32 repair_dividend;' in sources(text)[0] and 'repair_dividend /= 10;' in sources(text)[0]


def test_leaves_calls_loop_headers_and_floats():
    assert sources('void f(s32 *o) {\n    *o = (g() - 1) % 5;\n}\n') == []
    assert sources('void f(s32 *o, s32 a) {\n    if (*o) *o = (a - 1) % 5;\n}\n') == []
    assert sources('void f(f32 *o, f32 a) {\n    *o = (a - 1.0f) / 5;\n}\n') == []
    assert sources('void f(s32 *o, s32 a) {\n    *o = g(a - 1) % 5;\n}\n') == []
