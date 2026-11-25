"""callback_call_through_field: a callback stored in a field and then called by name is called through the field (jalr)."""
from decomprepair import callback_call_through_field as cb
from decomprepair import registry

SOURCE = '''void f(void *arg0) {
    void *temp_v0;
    void *temp_v1;

    temp_v0 = func_800232B4(1, 0, 0, 0);
    M2C_FIELD(temp_v0, M2C_UNK (**)(void *), 0x9C) = func_80080AF0;
    func_80080AF0(temp_v0);
    temp_v1 = func_800232B4(2, 0, 0, 0);
    M2C_FIELD(temp_v1, M2C_UNK **, 0x9C) = &func_80080AF0;
    func_80080AF0(temp_v1, 4);
}
'''
ASM = '''glabel f
/* 0 80001000 0040F809 */  jalr       $v0
/* 4 80001004 00000000 */  nop
endlabel f
'''


def test_each_pair_is_called_through_its_field_with_the_stored_type():
    out = cb.variants(SOURCE, 'f', ASM)
    assert [fam for fam, _ in out] == [cb.FAMILY, cb.FAMILY + '_one', cb.FAMILY + '_one']
    everything = out[0][1]
    assert '    M2C_FIELD(temp_v0, M2C_UNK (**)(void *), 0x9C)(temp_v0);\n' in everything
    assert '    ((void (*)()) M2C_FIELD(temp_v1, M2C_UNK **, 0x9C))(temp_v1, 4);\n' in everything
    assert 'func_80080AF0(temp_v' not in everything
    assert 'func_80080AF0(temp_v1, 4)' in out[1][1] and 'func_80080AF0(temp_v0)' not in out[1][1]


def test_nothing_without_a_jalr_or_when_the_target_calls_the_name_directly():
    assert cb.variants(SOURCE, 'f', ASM.replace('jalr       $v0', 'jr         $v0')) == []
    assert cb.variants(SOURCE, 'f', ASM + '/* 8 */  jal        func_80080AF0\n') == []


def test_a_call_that_is_not_the_stored_name_or_not_adjacent_is_left_alone():
    other = SOURCE.replace('    func_80080AF0(temp_v0);', '    func_other(temp_v0);')
    assert 'M2C_FIELD(temp_v0, M2C_UNK (**)' in other and len(cb.variants(other, 'f', ASM)[0][1].split('(temp_v0);')) == 2
    apart = SOURCE.replace('    func_80080AF0(temp_v0);', '    g();\n    func_80080AF0(temp_v0);')
    assert 'func_80080AF0(temp_v0);' in cb.variants(apart, 'f', ASM)[0][1]


def test_it_is_registered():
    assert any(r.module == 'callback_call_through_field' for r in registry.declared())
