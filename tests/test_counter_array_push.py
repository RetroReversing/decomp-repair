"""counter_array_push: a store into a global array at a global count, written through the old count with the array's pointer first."""
from decomprepair import counter_array_push as push
from decomprepair import registry

HEADER = 'extern s32 D_800DA840;\nextern char D_800DA848[];\n'
SAVED = HEADER + '''void func_8002338C(s32 arg0) {
    s32 *temp_v0;
    s32 temp_v1;
    u8 *bp;

    bp = D_800DA848;
    temp_v0 = bp - (-(D_800DA840 * 4));
    temp_v1 = D_800DA840 + 1;
    D_800DA840 = temp_v1;
    *temp_v0 = arg0;
    if (temp_v1 >= 0xC8) {
        D_800DA840 = 0xC7;
    }
}
'''
DRAFT = '''extern s32 D_800DA840;
extern M2C_UNK D_800DA848;

void func_8002338C(s32 arg0) {
    s32 *temp_v0;
    s32 temp_v1;

    temp_v0 = (D_800DA840 * 4) + &D_800DA848;
    temp_v1 = D_800DA840 + 1;
    D_800DA840 = temp_v1;
    *temp_v0 = arg0;
    if (temp_v1 >= 0xC8) {
        D_800DA840 = 0xC7;
    }
}
'''
MATCHED_BODY = '''    table = (s32 *)D_800DA848;
    slot = D_800DA840;
    table[slot] = arg0;
    D_800DA840 = slot + 1;
    if (slot + 1 >= 0xC8) {
        D_800DA840 = 0xC7;
    }
}
'''


def _children(source, name='func_8002338C'):
    return dict(push.variants(source, name))


def test_the_saved_best_gets_the_pointer_first_and_the_store_through_the_old_count():
    child = _children(SAVED)[push.FAMILY]
    assert child.endswith(MATCHED_BODY)
    assert '    s32 *table;\n    s32 slot;\n\n    table = ' in child
    assert 'temp_v0' not in child and 'temp_v1' not in child and 'bp' not in child


def test_the_draft_with_an_unknown_typed_symbol_is_read():
    child = _children(DRAFT)[push.FAMILY]
    assert 'table = (s32 *)&D_800DA848;' in child and 'table[slot] = arg0;' in child


def test_the_pointer_is_the_first_statement_even_when_the_base_was_assigned_late():
    source = SAVED.replace('    bp = D_800DA848;\n', '    D_800DA844 = 1;\n    bp = D_800DA848;\n')
    children = _children(source)
    assert children[push.FAMILY].index('table = (s32 *)D_800DA848;') < children[push.FAMILY].index('D_800DA844 = 1;')
    assert children[push.ORDER].index('D_800DA844 = 1;') < children[push.ORDER].index('table = (s32 *)D_800DA848;')
    assert children[push.BASE_FIRST].index('bp = D_800DA848;') < children[push.BASE_FIRST].index('D_800DA844 = 1;')


def test_a_base_declared_with_its_initialiser_and_other_spellings_of_the_sum_are_read():
    for spelling in ('(D_800DA840 << 2) + bp', 'bp + (D_800DA840 * 4)', 'bp - (-(D_800DA840 * 4))'):
        source = SAVED.replace('    u8 *bp;\n\n    bp = D_800DA848;\n', '    u8 *bp = D_800DA848;\n\n').replace('bp - (-(D_800DA840 * 4))', spelling)
        assert _children(source)[push.FAMILY].endswith(MATCHED_BODY), spelling


def test_later_reads_of_the_sum_follow_the_count_and_a_decrement_is_read():
    source = SAVED.replace('temp_v1 = D_800DA840 + 1;', 'temp_v1 = D_800DA840 - 1;').replace('        D_800DA840 = 0xC7;\n', '        D_800DA840 = temp_v1 * 2;\n')
    child = _children(source)[push.FAMILY]
    assert 'D_800DA840 = slot - 1;' in child and 'D_800DA840 = (slot - 1) * 2;' in child and 'if (slot - 1 >= 0xC8)' in child


def test_a_wrong_scale_a_word_array_or_other_statements_between_are_left_alone():
    assert not push.variants(SAVED.replace('* 4)', '* 8)'), 'func_8002338C')
    assert not push.variants(SAVED.replace('extern char D_800DA848[];', 'extern s32 D_800DA848[];').replace('    u8 *bp;', '    s32 *bp;'), 'func_8002338C')
    assert not push.variants(SAVED.replace('    D_800DA840 = temp_v1;\n', '    D_800DA840 = temp_v1;\n    D_800DA850 = 1;\n'), 'func_8002338C')


def test_a_value_that_is_the_count_a_second_use_of_the_pointer_or_a_volatile_count_is_left_alone():
    assert not push.variants(SAVED.replace('*temp_v0 = arg0;', '*temp_v0 = D_800DA840;'), 'func_8002338C')
    assert not push.variants(SAVED.replace('    if (temp_v1', '    D_800DA854 = *temp_v0;\n    if (temp_v1'), 'func_8002338C')
    assert not push.variants(SAVED.replace('extern s32 D_800DA840;', 'extern volatile s32 D_800DA840;'), 'func_8002338C')


def test_a_sum_that_is_written_again_after_the_store_is_left_alone():
    assert not push.variants(SAVED.replace('        D_800DA840 = 0xC7;', '        temp_v1 = 0;'), 'func_8002338C')


def test_the_module_declares_itself_for_the_registry():
    modules = {repair.module: repair for repair in registry.declared()}
    assert modules['counter_array_push'].families == push.FAMILIES
    assert 'header' in modules['counter_array_push'].needs
