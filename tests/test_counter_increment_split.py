"""counter_increment_split: a counter advanced after the stores into its own array element, the sum taken before the last store."""
from decomprepair import counter_increment_split as split
from decomprepair import registry

HEADER = 'extern s32 D_800B7690;\nextern char D_801407C8[];\n'
PLAIN = HEADER + '''void func_80048374(s32 arg0) {
    void *temp_v1;

    if (D_800B7690 >= 0x100) {
        func_800899DC();
    }
    { u8 *bp = D_801407C8; temp_v1 = bp + D_800B7690 * 8; }
    M2C_FIELD(temp_v1, s8 *, 4) = 0;
    M2C_FIELD(temp_v1, s32 *, 0) = arg0;
    D_800B7690 += 1;
}
'''
SCAFFOLD = PLAIN.replace('    { u8 *bp', '    do {\n    { u8 *bp').replace('    D_800B7690 += 1;', '    } while (0);\n    D_800B7690 += 1;')
MATCHED_TAIL = '''    { u8 *bp = D_801407C8; temp_v1 = bp + D_800B7690 * 8; }
    M2C_FIELD(temp_v1, s8 *, 4) = 0;
    count_next = D_800B7690 + 1;
    M2C_FIELD(temp_v1, s32 *, 0) = arg0;
    D_800B7690 = count_next;
}
'''


def _children(source, name='func_80048374'):
    return dict(split.variants(source, name))


def test_the_sum_goes_before_the_last_store_and_is_stored_last():
    child = _children(PLAIN)[split.FAMILY]
    assert child.endswith(MATCHED_TAIL)
    assert '    s32 count_next;\n    void *temp_v1;' in child


def test_an_earlier_position_is_its_own_child():
    child = _children(PLAIN)[split.EARLY]
    assert '    count_next = D_800B7690 + 1;\n    M2C_FIELD(temp_v1, s8 *, 4) = 0;' in child
    assert child.endswith('    D_800B7690 = count_next;\n}\n')


def test_the_other_spellings_of_the_increment_are_read():
    for spelling in ('D_800B7690 = D_800B7690 + 1;', 'D_800B7690++;', 'D_800B7690 = 1 + D_800B7690;'):
        assert _children(PLAIN.replace('D_800B7690 += 1;', spelling))[split.FAMILY].endswith(MATCHED_TAIL)
    child = _children(PLAIN.replace('D_800B7690 += 1;', 'D_800B7690 -= 2;'))[split.FAMILY]
    assert 'count_next = D_800B7690 - 2;' in child


def test_stores_in_a_do_while_zero_scaffold_get_the_unwrapped_child_too():
    children = _children(SCAFFOLD)
    assert children[split.UNWRAPPED].endswith(MATCHED_TAIL)
    assert 'do {' not in children[split.UNWRAPPED] and 'while (0)' not in children[split.UNWRAPPED]
    assert 'do {' in children[split.FAMILY] and children[split.FAMILY].endswith('    } while (0);\n    D_800B7690 = count_next;\n}\n')


def test_a_scaffold_with_a_break_is_kept():
    broken = SCAFFOLD.replace('M2C_FIELD(temp_v1, s32 *, 0) = arg0;', 'if (arg0) break;\n    M2C_FIELD(temp_v1, s32 *, 0) = arg0;')
    assert split.UNWRAPPED not in _children(broken)


def test_a_single_store_gets_the_sum_before_it():
    one = PLAIN.replace('    M2C_FIELD(temp_v1, s8 *, 4) = 0;\n', '')
    child = _children(one)[split.FAMILY]
    assert '    count_next = D_800B7690 + 1;\n    M2C_FIELD(temp_v1, s32 *, 0) = arg0;\n    D_800B7690 = count_next;' in child
    assert split.EARLY not in _children(one)


def test_the_field_and_pointer_spellings_of_a_store_are_read():
    for first in ('*(s8 *)(temp_v1 + 4) = 0;', 'temp_v1[0] = 0;', '*temp_v1 = 0;'):
        source = PLAIN.replace('void *temp_v1;', 's8 *temp_v1;').replace('M2C_FIELD(temp_v1, s8 *, 4) = 0;', first)
        assert split.FAMILY in _children(source), first


def test_what_is_not_this_shape_is_left_alone():
    # the element is not addressed from the count
    assert not split.variants(PLAIN.replace('bp + D_800B7690 * 8', 'bp + 8'), 'func_80048374')
    # the value stored reads the count, or the pointer
    assert not split.variants(PLAIN.replace('= arg0;', '= D_800B7690;'), 'func_80048374')
    # the count is volatile, a local, or not 32 bits wide
    assert not split.variants(PLAIN.replace('extern s32', 'extern volatile s32'), 'func_80048374')
    assert not split.variants(PLAIN.replace('extern s32', 'extern s16'), 'func_80048374')
    assert not split.variants(PLAIN.replace('void *temp_v1;', 'void *temp_v1;\n    s32 D_800B7690;'), 'func_80048374')
    # something else sits between the stores and the increment, or the stores are in a branch of their own
    assert not split.variants(PLAIN.replace('    D_800B7690 += 1;', '    func_800899DC();\n    D_800B7690 += 1;'), 'func_80048374')
    branch = PLAIN.replace('    M2C_FIELD(temp_v1, s8 *, 4) = 0;\n    M2C_FIELD(temp_v1, s32 *, 0) = arg0;',
                           '    if (arg0) {\n    M2C_FIELD(temp_v1, s8 *, 4) = 0;\n    M2C_FIELD(temp_v1, s32 *, 0) = arg0;\n    }')
    assert not split.variants(branch, 'func_80048374')
    # the increment is not by a constant
    assert not split.variants(PLAIN.replace('D_800B7690 += 1;', 'D_800B7690 += arg0;'), 'func_80048374')


def test_the_module_declares_itself_for_the_registry():
    modules = {repair.module: repair for repair in registry.declared()}
    assert modules['counter_increment_split'].families == split.FAMILIES
