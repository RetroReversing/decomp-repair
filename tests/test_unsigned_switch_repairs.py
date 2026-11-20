from decomprepair import unsigned_switch_repairs as r

DRAFT = '''void f(S *arg0, s32 arg1) {
    s32 v = arg0->flags & ~0xF0;
    switch (arg1) {
    case 0: v |= 0x10; break;
    case 1: v |= 0x20; break;
    case 3: v |= 0x80; break;
    default: return;
    }
    arg0->flags = v;
}
'''


def test_casts_the_switch_operand_unsigned():
    out = [t for _, t in r.variants(DRAFT, 'f')]
    assert out == [DRAFT.replace('switch (arg1)', 'switch ((u32)arg1)')]


def test_an_expression_operand_keeps_its_parentheses():
    out = [t for _, t in r.variants(DRAFT.replace('switch (arg1)', 'switch (arg1 - 2)'), 'f')]
    assert 'switch ((u32)(arg1 - 2))' in out[0]


def test_a_negative_or_symbolic_label_is_left_alone():
    assert r.variants(DRAFT.replace('case 3:', 'case -1:'), 'f') == []
    assert r.variants(DRAFT.replace('case 3:', 'case MODE:'), 'f') == []


def test_an_already_unsigned_operand_is_left_alone():
    assert r.variants(DRAFT.replace('switch (arg1)', 'switch ((u32)arg1)'), 'f') == []
