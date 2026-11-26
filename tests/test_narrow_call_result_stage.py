from decomprepair import narrow_call_result_stage as n
from decomprepair import registry

SOURCE = '''s16 get(void *);
void put(void *, s16);
extern u16 D_80001000[];

void func_80002000(s32 i) {
    put(&D_80001000[i], get(&D_80001000[i]) - D_80001000[i]);
}
'''


def test_the_result_is_staged_and_changed_before_the_call():
    children = [child for _, child in n.variants(SOURCE, 'func_80002000')]
    assert ('    {\n        s32 staged_result;\n        staged_result = get(&D_80001000[i]);\n'
            '        staged_result -= D_80001000[i];\n        put(&D_80001000[i], staged_result);\n    }') in children[0]
    assert 'put(&D_80001000[i], (staged_result - D_80001000[i]));' in children[1]


def test_a_cast_stays_on_the_argument_and_the_header_may_declare_the_result():
    source = '''void func_80002000(void *p, s32 x) {
    put(p, (s16) (get(p) + x));
}
'''
    child = n.variants(source, 'func_80002000', header='short get(void *);')[0][1]
    assert 'staged_result += x;' in child and 'put(p, (s16) staged_result);' in child


def test_a_word_result_another_call_or_a_longer_expression_is_left_alone():
    assert n.variants(SOURCE.replace('s16 get', 's32 get'), 'func_80002000') == []
    assert n.variants(SOURCE.replace('&D_80001000[i], get', 'other(i), get'), 'func_80002000') == []
    assert n.variants(SOURCE.replace('- D_80001000[i])', '- D_80001000[i] + 1)'), 'func_80002000') == []


def test_an_unbraced_arm_is_left_alone():
    assert n.variants(SOURCE.replace('    put(&', '    if (i)\n    put(&'), 'func_80002000') == []


def test_declared_in_the_registry():
    assert any(entry.module == 'narrow_call_result_stage' for entry in registry.declared())


def test_a_cast_before_a_parenthesis_is_not_a_call():
    source = SOURCE.replace('- D_80001000[i])', '- *(u16 *)((u8 *)D_80001000 + i * 2))')
    assert 'staged_result -= *(u16 *)((u8 *)D_80001000 + i * 2);' in n.variants(source, 'func_80002000')[0][1]
