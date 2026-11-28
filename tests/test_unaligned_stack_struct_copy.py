"""m2c's unaligned words copied to separate stack locals, as the struct assignment they were."""
from decomprepair import registry
from decomprepair import unaligned_stack_struct_copy as copies

SOURCE = '''extern M2C_UNK D_80001000;
s32 check(void)
{
    M2C_UNK sp18;
    M2C_UNK sp1C;
    M2C_UNK sp20;
    M2C_UNK sp24;
    M2C_UNK sp28;

    sp18 = M2C_UNALIGNED32(M2C_FIELD(&D_80001000, M2C_UNK *, 0));
    sp1C = M2C_UNALIGNED32(M2C_FIELD(&D_80001000, M2C_UNK *, 4));
    sp20 = M2C_UNALIGNED32(M2C_FIELD(&D_80001000, M2C_UNK *, 8));
    sp24 = M2C_UNALIGNED32(M2C_FIELD(&D_80001000, M2C_UNK *, 0xC));
    clear(&sp28);
    return find(&sp18, &sp28);
}
'''


def children(source=SOURCE):
    found = copies.variants(source, 'check')
    assert all(family == copies.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_words_become_one_byte_record_assignment():
    child, = children()
    assert '    sp18 = *(__repair_bytes16 *) &D_80001000;\n' in child
    assert '    __repair_bytes16 sp18;\n    M2C_UNK sp28;\n' in child
    assert child.index('typedef struct { char data[16]; } __repair_bytes16;') < child.index('s32 check(')
    assert 'M2C_UNALIGNED32' not in child and 'sp1C' not in child


def test_a_source_pointer_with_an_offset():
    source = SOURCE.replace('&D_80001000, M2C_UNK *, 0)', 'ptr, M2C_UNK *, 8)')
    source = source.replace('&D_80001000, M2C_UNK *, 4)', 'ptr, M2C_UNK *, 0xC)')
    child, = children(source.replace('    sp20 = M2C_UNALIGNED32(M2C_FIELD(&D_80001000, M2C_UNK *, 8));\n', '')
                      .replace('    sp24 = M2C_UNALIGNED32(M2C_FIELD(&D_80001000, M2C_UNK *, 0xC));\n', ''))
    assert '    sp18 = *(__repair_bytes8 *) ((char *) ptr + 0x8);\n' in child


TWO_ARMS = SOURCE.replace('s32 check(void)', 's32 check(s32 which)').replace('''    clear(&sp28);
''', '''    if (which == 0) {
        sp18 = M2C_UNALIGNED32(M2C_FIELD(&D_80002000, M2C_UNK *, 0));
        sp1C = M2C_UNALIGNED32(M2C_FIELD(&D_80002000, M2C_UNK *, 4));
        sp20 = M2C_UNALIGNED32(M2C_FIELD(&D_80002000, M2C_UNK *, 8));
        sp24 = M2C_UNALIGNED32(M2C_FIELD(&D_80002000, M2C_UNK *, 0xC));
    }
    clear(&sp28);
''')


def test_arms_copying_into_the_same_words_share_the_record():
    child, = children(TWO_ARMS)
    assert '    sp18 = *(__repair_bytes16 *) &D_80001000;\n' in child
    assert '        sp18 = *(__repair_bytes16 *) &D_80002000;\n' in child
    assert child.count('__repair_bytes16 sp18;') == 1
    assert 'M2C_UNALIGNED32' not in child and 'sp1C' not in child and 'sp24' not in child


def test_runs_of_different_sizes_into_the_same_words_decline():
    source = TWO_ARMS.replace('        sp24 = M2C_UNALIGNED32(M2C_FIELD(&D_80002000, M2C_UNK *, 0xC));\n', '')
    assert children(source) == []


def test_a_later_word_read_elsewhere_declines():
    assert children(SOURCE.replace('clear(&sp28);', 'clear(sp1C);')) == []


def test_the_first_word_read_as_a_value_declines():
    assert children(SOURCE.replace('find(&sp18,', 'find(sp18,')) == []
    assert children(SOURCE.replace('find(&sp18,', 'find(x && sp18,')) == []


def test_words_apart_on_the_stack_are_left_alone():
    child, = children(SOURCE.replace('sp1C', 'sp40'))
    assert '    sp20 = *(__repair_bytes8 *) ((char *) &D_80001000 + 0x8);\n' in child
    assert children(SOURCE.replace('M2C_UNK *, 4)', 'M2C_UNK *, 0x20)')
                    .replace('M2C_UNK *, 0xC)', 'M2C_UNK *, 0x40)')) == []


def test_the_family_is_registered():
    assert any(copies.FAMILY in repair.families for repair in registry.declared())
