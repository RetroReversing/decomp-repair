from decomprepair.ternary_result_branches import variants

SOURCE = '''extern volatile s32 D_80000000;
void func_80000000(void) {
    D_80000000 = D_80000000 >= 0x22 ? 0x22 : D_80000000 + 0xA;
}
'''


def test_both_arm_orders():
    texts = [text for _, text in variants(SOURCE, 'func_80000000')]
    assert len(texts) == 2
    assert 'if (D_80000000 >= 0x22) {\n            chosen = 0x22;' in texts[0]
    assert 'if (D_80000000 < 0x22) {\n            chosen = D_80000000 + 0xA;' in texts[1]
    assert all('D_80000000 = chosen;' in t and '?' not in t for t in texts)


def test_index_lvalue_and_nested_ternary():
    source = 'void f(s32 i) {\n    D_1[i] = (i != 0) ? i : 4;\n    D_2 = i ? i ? 1 : 2 : 3;\n}\n'
    out = variants(source, 'f')
    assert len(out) == 2
    assert 'D_1[i] = chosen;' in out[0][1]


def test_nothing_without_a_conditional():
    assert variants('void f(s32 i) {\n    D_1 = i;\n}\n', 'f') == []
