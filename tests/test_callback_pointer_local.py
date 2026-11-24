"""callback_pointer_local: a callback stored into a record and called back through it, with the pointer in a local."""
from decomprepair import callback_pointer_local as cpl
from decomprepair import registry

NAME = 'func_80020000'
SOURCE = '''void func_80021000(void *);                         /* extern */

void func_80020000(void *arg0, void *arg1) {
    void *temp_a;

    M2C_FIELD(arg1, void (**)(void *), 0xA0) = &func_80021000;
    temp_a = M2C_FIELD(arg0, void *, 0x4);
    M2C_FIELD(arg0, void (**)(void *), 0xA0)(arg0);
}
'''
ASM = '''
glabel func_80020000
    /* 0 */  lui        $v0, %hi(func_80021000)
    /* 4 */  addiu      $v0, $v0, %lo(func_80021000)
    /* 8 */  sw         $v0, 0xA0($a1)
    /* c */  lw         $v1, 0xA0($a0)
    /* 10 */  nop
    /* 14 */  jalr       $v1
    /* 18 */   nop
    /* 1c */  jr         $ra
    /* 20 */   nop
endlabel func_80020000
'''


def _children(source=SOURCE, asm=ASM, **kw):
    return cpl.variants(source, NAME, asm=asm, **kw)


def test_the_target_calls_through_the_field_and_builds_the_address():
    assert cpl.evidence(ASM) == ({0xA0}, {'func_80021000'})
    assert _children(asm='') == []
    assert _children(asm=ASM.replace('jalr       $v1', 'jr         $v1'))  # (jr through the register is a tail call: still through the field)
    assert _children(asm=ASM.replace('jalr       $v1', 'nop')) == []
    assert _children(asm=ASM.replace('0xA0($a0)', '0xA4($a0)')) == []


def test_the_call_reads_the_field_into_a_function_pointer_local():
    family, text = next(c for c in _children() if c[0] == cpl.FAMILY)
    assert 'void (*callback_fn)(void *);' in text
    assert 'callback_fn = M2C_FIELD(arg0, void (**)(void *), 0xA0);\n    callback_fn(arg0);' in text
    assert '= &func_80021000;' in text  # (the store is left alone in this child)


def test_the_store_at_the_same_offset_goes_through_it_too_for_a_second_assignment():
    text = next(t for f, t in _children() if f == cpl.STORE_FAMILY)
    assert 'callback_fn = &func_80021000;\n    M2C_FIELD(arg1, void (**)(void *), 0xA0) = callback_fn;' in text
    assert text.count('callback_fn =') == 2 and 'callback_fn(arg0);' in text


def test_an_assigned_result_and_other_arguments():
    source = SOURCE.replace('M2C_FIELD(arg0, void (**)(void *), 0xA0)(arg0);', 'temp_a = M2C_FIELD(arg0, s32 (**)(void *, s32), 0xA0)(arg0, 3);').replace(
        'void (**)(void *), 0xA0) = &', 'void (**)(void *), 0xA0) = &')
    text = next(t for f, t in _children(source) if f == cpl.FAMILY)
    assert 's32 (*callback_fn)(void *, s32);' in text and 'temp_a = callback_fn(arg0, 3);' in text
    assert any(f == cpl.STORE_FAMILY for f, _ in _children(source))  # (the field types need not read the same)


def test_declines_what_is_not_the_shape():
    no_symbol = ASM.replace('lui        $v0, %hi(func_80021000)', 'lui        $v0, 0x8002')
    assert _children(asm=no_symbol) == []  # (the target does not build the stored function's address)
    assert _children(SOURCE.replace('M2C_FIELD(arg0, void (**)(void *), 0xA0)(arg0);', 'M2C_FIELD(arg0, s32 *, 0xA0) = 1;')) == []
    assert _children(SOURCE.replace('func_80021000(void *);  ', 'func_80021001(void *);  ')) == []  # (the stored name is no function)
    assert _children(SOURCE.replace('    M2C_FIELD(arg1, void (**)(void *), 0xA0) = &func_80021000;\n', '')) == []  # (no store of a callback)
    nested = SOURCE.replace('(arg0);\n}', '(M2C_FIELD(arg0, s32 *, 0));\n}')
    assert _children(nested)  # (arguments may hold fields)


def test_registered_and_needs_the_assembly():
    found = {r.module: r for r in registry.declared()}['callback_pointer_local']
    assert set(found.families) == set(cpl.FAMILIES) and 'asm' in found.needs


def test_each_earlier_store_at_the_offset_is_a_child_and_a_code_symbol_declared_as_data_counts():
    source = SOURCE.replace('    temp_a = ', '    M2C_FIELD(arg1, void (**)(void *), 0xA0) = &func_80021002;\n    temp_a = ').replace(
        'void func_80021000(void *);  ', 'extern M2C_UNK func_80021002;\nvoid func_80021000(void *);  ')
    asm = ASM.replace('/* 4 */', '/* 4 */  lui $v1, %hi(func_80021002)\n    /* 4 */')
    stores = [t for f, t in _children(source, asm) if f == cpl.STORE_FAMILY]
    assert len(stores) == 2
    assert 'callback_fn = &func_80021000;' in stores[0] and 'callback_fn = &func_80021002;' in stores[1]
