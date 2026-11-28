from decomprepair import registry
from decomprepair import zero_difference_locals as family

DRAFT = """s32 f(void *arg0) {
    s16 temp_a1;
    s16 temp_a2;

    temp_a2 = M2C_FIELD(arg0, s16 *, 0);
    temp_a1 = M2C_FIELD(arg0, s16 *, 2);
    if (((M2C_FIELD(arg0, s16 *, 4) == temp_a2) && ((M2C_FIELD(arg0, s16 *, 6) - temp_a1) == 0)) || (((M2C_FIELD(arg0, s16 *, 8) - temp_a2) == 0) && ((M2C_FIELD(arg0, s16 *, 0xA) - temp_a1) != 0))) {
        return 1;
    }
    return 0;
}
"""


def children(source, header=''):
    return family.variants(source, 'f', header)


def test_the_differences_are_named_in_order_before_the_if():
    kids = children(DRAFT)
    assert [kind for kind, _ in kids] == ['zero_difference_locals', 'zero_difference_locals_wide',
                                          'zero_difference_locals_all', 'zero_difference_locals_wide']
    first = kids[0][1]
    assert ('    zdiff0 = M2C_FIELD(arg0, s16 *, 6) - temp_a1;\n'
            '    zdiff1 = M2C_FIELD(arg0, s16 *, 8) - temp_a2;\n'
            '    zdiff2 = M2C_FIELD(arg0, s16 *, 0xA) - temp_a1;\n'
            '    if (') in first
    assert '(zdiff2 != 0)' in first and 'M2C_FIELD(arg0, s16 *, 4) == temp_a2' in first
    assert 's16 temp_a1;' in first


def test_every_test_of_the_condition_and_the_wide_temporaries_come_together():
    wide = children(DRAFT)[3][1]
    assert 'zdiff0 = M2C_FIELD(arg0, s16 *, 4) - temp_a2;' in wide and '(zdiff3 != 0)' in wide
    assert 's32 temp_a1;' in wide and 's32 temp_a2;' in wide
    assert wide.count('s32 zdiff') == 4


def test_a_narrow_temporary_that_could_truncate_stays_narrow():
    source = DRAFT.replace('temp_a1 = M2C_FIELD(arg0, s16 *, 2);', 'temp_a1 = M2C_FIELD(arg0, s32 *, 2);')
    wide = [text for kind, text in children(source) if kind == 'zero_difference_locals_wide']
    assert all('s16 temp_a1;' in text for text in wide)


def test_member_reads_need_integer_members():
    source = """s32 f(P *p) {
    s32 x;
    x = p->x0;
    if (((p->x1 - x) == 0) && ((p->x2 - x) == 0)) {
        return 1;
    }
    return 0;
}
"""
    assert children(source, 'typedef struct { short x0, x1, x2; } P;')
    assert children(source, 'typedef struct { float x0, x1, x2; } P;') == []
    assert children(source) == []


def test_a_float_difference_is_not_hoisted():
    for _, text in children(DRAFT.replace('s16 temp_a1;', 'f32 temp_a1;')):
        assert '- temp_a1;' not in text


def test_the_first_test_of_the_condition_counts_as_a_read():
    source = "s32 f(s32 *q, s32 k) {\n    if ((*(s32 *) q == k) && ((*(s32 *) (q + 4) - k) == 0)) {\n        return 1;\n    }\n    return 0;\n}\n"
    assert children(source)


def test_a_read_that_a_guard_protects_is_not_made_unconditional():
    source = """s32 f(s32 *p, s32 *q, s32 k) {
    if ((q != NULL) && ((*(s32 *) (q + 4) - k) == 0)) {
        return 1;
    }
    return 0;
}
"""
    assert children(source) == []


def test_a_condition_with_a_call_or_an_assignment_is_left_alone():
    assert children(DRAFT.replace('- temp_a1) == 0', '- (temp_a1 = 2)) == 0')) == []
    assert children(DRAFT.replace('== temp_a2) &&', '== g(temp_a2)) &&')) == []


def test_an_else_if_is_left_alone():
    assert children(DRAFT.replace('    if (', '    if (temp_a1) {\n    } else if (')) == []


def test_it_declares_itself():
    assert registry.get('zero_difference_locals').families == family.FAMILIES
