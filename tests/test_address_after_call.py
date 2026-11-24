"""address_after_call: a store of a call's value at a global table's base plus a scaled index, the call first and the base in its own pointer."""
from decomprepair import address_after_call as repair
from decomprepair import registry

HEADER = 'extern char D_800AC3D0[];\ns32 func_80023D58();\n'
SCAFFOLD = HEADER + '''s32 func_80023A98(s32 arg0, s32 arg1, s32 arg2) {
    void *temp_s0;

    { { M2C_FIELD((temp_s0 = (arg0 * 0x10) + D_800AC3D0), s32 *, 0) = func_80023D58(arg1); } }
    { M2C_FIELD(temp_s0, s32 *, 0xC) = arg2; }
    return 1;
}
'''
SAVED = HEADER + '''s32 func_80023A98(s32 arg0, s32 arg1, s32 arg2) {
    void *temp_s0;

    M2C_FIELD((temp_s0 = (arg0 * 0x10) + D_800AC3D0), s32 *, 0) = func_80023D58(arg1);
    M2C_FIELD(temp_s0, s32 *, 0xC) = arg2;
    return 1;
}
'''
DRAFT = '''s32 func_80023D58(M2C_UNK);
extern M2C_UNK D_800AC3D0;

s32 func_80023A98(s32 arg0, M2C_UNK arg1, s32 arg2) {
    void *temp_s0;

    temp_s0 = (arg0 * 0x10) + &D_800AC3D0;
    M2C_FIELD(temp_s0, s32 *, 0) = func_80023D58(arg1);
    M2C_FIELD(temp_s0, s32 *, 0xC) = arg2;
    return 1;
}
'''
MATCHED_BODY = '''    call_value = func_80023D58(arg1);
    table_base = D_800AC3D0;
    temp_s0 = (arg0 * 0x10) + table_base;
    M2C_FIELD(temp_s0, s32 *, 0) = call_value;
    M2C_FIELD(temp_s0, s32 *, 0xC) = arg2;
    return 1;
'''


def _children(source, name='func_80023A98'):
    return dict(repair.variants(source, name))


def test_saved_best_gives_the_call_then_the_base_then_the_sum():
    child = _children(SAVED)[repair.AFTER]
    assert MATCHED_BODY in child
    assert '    s32 call_value;\n    char *table_base;\n' in child
    assert 'void *temp_s0;' in child


def test_the_base_may_be_held_across_the_call():
    child = _children(SAVED)[repair.BEFORE]
    assert '    table_base = D_800AC3D0;\n    call_value = func_80023D58(arg1);\n    temp_s0 = (arg0 * 0x10) + table_base;\n' in child


def test_a_scaffolded_best_keeps_its_braces():
    child = _children(SCAFFOLD)[repair.AFTER]
    assert child.startswith(HEADER) and '{ { call_value = func_80023D58(arg1);\n' in child
    assert 'M2C_FIELD(temp_s0, s32 *, 0) = call_value;\n } }\n    { M2C_FIELD(temp_s0, s32 *, 0xC) = arg2; }' in child


def test_the_drafts_address_statement_and_store_are_one_site():
    child = _children(DRAFT)[repair.AFTER]
    assert child.index('call_value = func_80023D58(arg1);') < child.index('table_base = &D_800AC3D0;') < child.index('temp_s0 = (arg0 * 0x10) + table_base;')
    assert 'M2C_UNK *table_base;' in child
    assert child.count('temp_s0 = ') == 1


def test_the_symbol_first_spelling_keeps_its_operand_order():
    source = SAVED.replace('(arg0 * 0x10) + D_800AC3D0', 'D_800AC3D0 + (arg0 << 4)')
    assert 'temp_s0 = table_base + (arg0 << 4);' in _children(source)[repair.AFTER]


def test_a_left_side_dereference_is_a_site():
    source = HEADER + '''void func_80023A98(s32 arg0, s32 arg1) {
    s32 *slot;

    *(slot = (s32 *)((arg0 * 4) + D_800AC3D0)) = func_80023D58(arg1);
}
'''
    assert not _children(source)  # (a cast around the sum is not one of the spellings)
    source = source.replace('(s32 *)((arg0 * 4) + D_800AC3D0)', '(arg0 * 4) + D_800AC3D0')
    child = _children(source)[repair.AFTER]
    assert '*slot = call_value;' in child and 'slot = (arg0 * 4) + table_base;' in child


def test_family_names_are_the_registrys():
    assert set(repair.FAMILIES) == {repair.AFTER, repair.BEFORE}
    assert registry.get('address_after_call').families == repair.FAMILIES


def test_a_global_index_is_left_alone():
    source = SAVED.replace('arg0 * 0x10', 'D_800AC3D4 * 0x10').replace('extern char', 'extern s32 D_800AC3D4;\nextern char')
    assert not _children(source)  # the call may change the global the index reads


def test_an_index_the_call_writes_or_whose_address_is_taken_is_left_alone():
    assert not _children(SAVED.replace('func_80023D58(arg1)', 'func_80023D58(arg0++)'))
    assert not _children(SAVED.replace('func_80023D58(arg1)', 'func_80023D58(&arg0)'))


def test_a_call_that_reads_the_pointer_is_left_alone():
    assert not _children(SAVED.replace('func_80023D58(arg1)', 'func_80023D58(temp_s0)'))
    assert not _children(DRAFT.replace('func_80023D58(arg1)', 'func_80023D58(temp_s0)'))


def test_a_value_without_a_call_is_left_alone():
    assert not _children(SAVED.replace('func_80023D58(arg1)', 'arg1'))


def test_a_pointer_global_or_an_unknown_table_is_left_alone():
    assert not _children(SAVED.replace('extern char D_800AC3D0[];', 'extern char *D_800AC3D0;'))
    assert not _children(SAVED.replace('extern char D_800AC3D0[];', ''))
    assert not _children(SAVED.replace('extern char D_800AC3D0[];', 'extern char D_800AC3D0;'))


def test_a_store_that_is_the_body_of_an_if_is_left_alone():
    source = SAVED.replace('    M2C_FIELD((temp_s0', '    if (arg2)\n        M2C_FIELD((temp_s0')
    assert not _children(source)


def test_a_volatile_or_asm_function_is_left_alone():
    assert not _children(SAVED.replace('void *temp_s0;', 'volatile s32 x;\n    void *temp_s0;'))


def test_the_name_is_the_functions():
    assert not repair.variants(SAVED, 'func_80023ABC')


def test_the_registry_runs_it():
    entry = registry.get('address_after_call')
    assert registry.problems(entry) == []
    assert entry.needs == ('source', 'name', 'header')
