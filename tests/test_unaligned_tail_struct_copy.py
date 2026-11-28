"""m2c's unaligned word plus byte tail of one constant, as the record assignment it was."""
from decomprepair import registry
from decomprepair import unaligned_tail_struct_copy as tail

SOURCE = '''extern M2C_UNK D_80001000;
void load(s32 index)
{
    M2C_UNK sp28;
    s8 sp2C;
    s8 sp2D;
    M2C_UNK temp_a3;

    temp_a3 = M2C_UNALIGNED32(M2C_FIELD(&D_80001000, M2C_UNK *, 0));
    sp28 = temp_a3;
    sp2C = M2C_FIELD(&D_80001000, s8 *, 4);
    sp2D = M2C_FIELD(&D_80001000, s8 *, 5);
    take(*(&sp28 + index));
}
'''


def children(source):
    found = tail.variants(source, 'load')
    assert all(family == tail.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_word_and_tail_become_one_record_assignment():
    child, = children(SOURCE)
    assert '    sp28 = *(__repair_bytes6 *) &D_80001000;\n    take(*((u8 *) &sp28 + index));\n' in child
    assert '    __repair_bytes6 sp28;\n\n' in child
    assert child.index('typedef struct { char data[6]; } __repair_bytes6;') < child.index('void load(')
    assert 'temp_a3' not in child and 'sp2C' not in child and 'M2C_UNALIGNED32' not in child


def test_a_temporary_read_later_reads_the_record():
    child, = children(SOURCE.replace('take(*(&sp28 + index));', 'take(*(&sp28 + index), temp_a3);'))
    assert ('    sp28 = *(__repair_bytes6 *) &D_80001000;\n    temp_a3 = ((s32 *) &sp28)[0];\n'
            '    take(*((u8 *) &sp28 + index), temp_a3);\n') in child
    assert 'M2C_UNK temp_a3;' in child and 'M2C_UNALIGNED32' not in child


def test_declines_a_temporary_written_again():
    assert children(SOURCE.replace('take(*(&sp28 + index));', 'temp_a3 = 1;\n    take(temp_a3);')) == []
    assert children(SOURCE.replace('take(*(&sp28 + index));', 'take(&temp_a3);')) == []


def test_a_direct_word_and_a_half_tail():
    source = SOURCE.replace('    temp_a3 = M2C_UNALIGNED32', '    sp28 = M2C_UNALIGNED32').replace(
        '    sp28 = temp_a3;\n', '').replace('M2C_FIELD(&D_80001000, s8 *, 4)', 'M2C_FIELD(&D_80001000, s16 *, 4)')
    child, = children(source.replace('    sp2D = M2C_FIELD(&D_80001000, s8 *, 5);\n', ''))
    assert 'sp28 = *(__repair_bytes6 *) &D_80001000;' in child


def test_declines_uses_a_record_would_break():
    assert children(SOURCE.replace('take(*(&sp28 + index));', 'take(sp2C);')) == []
    assert children(SOURCE.replace('take(*(&sp28 + index));', 'take(sp28);')) == []
    assert children(SOURCE.replace('    M2C_UNK sp28;', '    s32 sp28;')) == []
    assert children(SOURCE.replace('&D_80001000, s8 *, 4', '&D_80002000, s8 *, 4')) == []


def test_whole_words_alone_are_left_to_the_other_family():
    source = SOURCE.replace('    sp2C = M2C_FIELD(&D_80001000, s8 *, 4);\n', '')
    assert children(source.replace('    sp2D = M2C_FIELD(&D_80001000, s8 *, 5);\n', '')) == []


def test_it_is_declared():
    assert any(tail.FAMILY in entry.families for entry in registry.declared())
