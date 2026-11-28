from decomprepair import compare_call_operand_local as repair

FLAG = '''void f(Obj *obj) {
    if (obj->level >= (isHard() != 0)) {
        spawn(obj);
    } else if (obj->level >= (u32) (isHard() != 0)) {
        drop(obj);
    }
}
'''

PICK = '''void f(Obj *obj) {
    if (obj->level >= (isHard() ? 2 : 1) && gPause == 0) {
        spawn(obj);
    }
}
'''


def test_flag_operand_is_held_before_the_if():
    texts = [text for _, text in repair.variants(FLAG, 'f')]
    assert any('u32 call_operand = isHard() != 0;' in text and 'if (obj->level >= call_operand)' in text
               for text in texts)
    assert any(text.count(' = isHard() != 0;') == 2 for text in texts)
    for text in texts:
        assert text.count('{') == text.count('}')


def test_picked_constant_is_set_then_replaced():
    texts = [text for _, text in repair.variants(PICK, 'f')]
    assert any('u32 call_operand = 2;' in text and 'if (isHard() == 0) { call_operand = 1; }' in text
               and 'if (obj->level >= call_operand && gPause == 0)' in text for text in texts)


def test_operand_behind_a_short_circuit_stays():
    source = '''void f(Obj *obj) {
    if (gPause == 0 && obj->level >= (isHard() != 0)) {
        spawn(obj);
    }
}
'''
    assert repair.variants(source, 'f') == []


def test_plain_comparisons_have_no_children():
    assert repair.variants('void f(int a) {\n    if (a >= 2) {\n        g();\n    }\n}\n', 'f') == []
