from decomprepair import registry
from decomprepair.arm_byte_copy_split import FAMILY, variants

SOURCE = """s32 voices(void *arg0, Entity *e, s32 count) {
    s32 i;
    u8 idx;
    u8 slot;
    void *rec;
    rec = arg0;
    i = 0;
    do {
        idx = *((u8 *) (((char *) rec) + 4));
        slot = i & 0xFF;
        if (slot != 9) {
            e->first[slot] = *((u8 *) (((char *) (idx + e)) + 8));
        } else {
            e->second = *((u8 *) (((char *) (idx + e)) + 0x8C));
        }
        rec += 8;
        i += 1;
    } while (i < count);
    return i;
}
"""


def children(source=SOURCE):
    return [c for f, c in variants(source, 'voices') if f == FAMILY]


def test_the_first_arm_reads_a_narrow_copy_of_a_widened_byte():
    got = children()
    assert len(got) == 2
    first = got[0]
    assert 's32 idx;' in first and 'u8 idx_byte;' in first
    assert first.index('idx_byte = idx;') < first.index('if (slot != 9)')
    arm = first[first.index('if (slot != 9)'):first.index('} else {')]
    assert 'idx_byte' in arm and 'idx +' not in arm
    assert 'idx + e' in first[first.index('} else {'):]
    second = got[1]
    arm = second[second.index('} else {'):]
    assert 'idx_byte + e' in arm
    assert 'idx + e' in second[second.index('if (slot != 9)'):second.index('} else {')]


def test_a_local_that_is_assigned_something_else_is_left_alone():
    assert children(SOURCE.replace('slot = i & 0xFF;', 'slot = i & 0xFF;\n        idx = idx + 1;')) == []


def test_a_byte_that_is_not_read_in_both_arms_is_left_alone():
    assert children(SOURCE.replace('(idx + e)) + 0x8C', '(e)) + 0x8C')) == []


def test_a_goto_elsewhere_in_the_function_does_not_stop_it():
    tail = SOURCE.replace('    return i;', '    if (i > 99) goto done;\n    i = 0;\ndone:\n    return i;')
    assert len(children(tail)) == 2


def test_a_label_between_the_byte_and_the_branch_stops_it():
    assert children(SOURCE.replace('slot = i & 0xFF;', 'again:\n        slot = i & 0xFF;')) == []


def test_a_byte_declared_wide_keeps_its_type_and_gets_the_narrow_copy():
    wide = SOURCE.replace('u8 idx;', 's32 idx;')
    first = children(wide)[0]
    assert first.count('s32 idx;') == 1 and 'u8 idx_byte;' in first


def test_the_family_declares_itself():
    assert FAMILY in {family for entry in registry.declared() for family in entry.families}
