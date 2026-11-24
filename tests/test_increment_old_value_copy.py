"""increment_old_value_copy: a loaded value stored plus a constant and tested afterwards, its old value held in a local of its own."""
from decomprepair import increment_old_value_copy as copy
from decomprepair import registry

SOURCE = '''#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern void *D_800B3960;
extern s32 func_80023078;
void func_80074F74(void *arg0) {
    s32 temp_v0;

    M2C_FIELD(D_800B3960, s32 *, 0x9C) = (s32) &func_800340B4;
    temp_v0 = M2C_FIELD(arg0, s32 *, 0x8C);
    M2C_FIELD(arg0, s32 *, 0x8C) = (s32) (temp_v0 + 1);
    if (temp_v0 >= 0xB) {
        M2C_FIELD(arg0, s32 *, 0x9C) = (s32) (&func_80023078 + 2);
    }
}
'''

COPY = '''    temp_v0 = M2C_FIELD(arg0, s32 *, 0x8C);
    temp_v0_old = temp_v0;
    temp_v0 = temp_v0 + 1;
    M2C_FIELD(arg0, s32 *, 0x8C) = temp_v0;
    if (temp_v0_old >= 0xB) {'''


def _by_family(source):
    return dict(copy.variants(source, 'func_80074F74'))


def test_the_old_value_is_copied_before_an_in_place_increment_and_the_test_reads_the_copy():
    child = _by_family(SOURCE)[copy.FAMILY]
    assert COPY in child
    assert 's32 temp_v0_old;' in child


def test_a_load_two_statements_above_gets_the_early_copy_too():
    source = SOURCE.replace('    M2C_FIELD(arg0, s32 *, 0x8C) = (s32)', '    D_800B3964 = 7;\n    M2C_FIELD(arg0, s32 *, 0x8C) = (s32)')
    children = _by_family(source)
    early = children[copy.EARLY]
    assert early.index('temp_v0_old = temp_v0;') < early.index('D_800B3964 = 7;')
    assert 'temp_v0 = temp_v0 + 1;' in early
    assert copy.FAMILY in children


def test_every_later_read_goes_to_the_copy_and_other_spellings_of_the_sum_are_read():
    source = SOURCE.replace('(s32) (temp_v0 + 1)', '4 + temp_v0').replace('    }\n', '    }\n    D_800B3968 = temp_v0 - 2;\n')
    child = _by_family(source)[copy.FAMILY]
    assert 'temp_v0 = temp_v0 + 4;' in child
    assert 'D_800B3968 = temp_v0_old - 2;' in child


def test_a_copy_already_there_gets_its_increment_in_place():
    source = SOURCE.replace('    temp_v0 = M2C', '    temp_v0 = M2C', 1).replace(
        '    M2C_FIELD(arg0, s32 *, 0x8C) = (s32) (temp_v0 + 1);\n    if (temp_v0 >= 0xB)',
        '    temp_v1 = temp_v0;\n    M2C_FIELD(arg0, s32 *, 0x8C) = temp_v0 + 1;\n    if (temp_v1 >= 0xB)').replace(
        '    s32 temp_v0;\n', '    s32 temp_v0;\n    s32 temp_v1;\n')
    children = _by_family(source)
    assert list(children) == [copy.IN_PLACE]
    assert '    temp_v0 = temp_v0 + 1;\n    M2C_FIELD(arg0, s32 *, 0x8C) = temp_v0;\n    if (temp_v1 >= 0xB)' in children[copy.IN_PLACE]


def test_nothing_is_offered_when_the_rewrite_could_change_the_program():
    later_write = SOURCE.replace('    }\n}', '    }\n    temp_v0 = 3;\n}')
    label = SOURCE.replace('    }\n}', '    }\nblock_9:\n    D_1 = temp_v0;\n}')
    narrow = SOURCE.replace('s32 temp_v0;', 's16 temp_v0;')
    no_read = SOURCE.replace('if (temp_v0 >= 0xB)', 'if (D_2 >= 0xB)')
    no_load = SOURCE.replace('    temp_v0 = M2C_FIELD(arg0, s32 *, 0x8C);\n', '')
    mentions = SOURCE.replace('M2C_FIELD(arg0, s32 *, 0x8C) = (s32) (temp_v0 + 1)', 'M2C_FIELD(arg0, s32 *, temp_v0) = (s32) (temp_v0 + 1)')
    address = SOURCE.replace('if (temp_v0 >= 0xB)', 'if (g(&temp_v0) >= 0xB)')
    for source in (later_write, label, narrow, no_read, no_load, mentions, address):
        assert copy.variants(source, 'func_80074F74') == []


def test_it_declares_itself_for_the_callers():
    declared = {repair.module for repair in registry.declared()}
    assert 'increment_old_value_copy' in declared
