"""m2c's `*((i * 2) + T) = 0;` on a `char T[]` is a halfword table (an effect update, `sb` where the target had `sh`)."""
from decomprepair.scaled_byte_table import FAMILY, variants

SOURCE = """extern char D_80100000[];

void f(void *arg0)
{
    *((M2C_FIELD(arg0, u8 *, 0x6E) * 2) + D_80100000) = 0;
}
"""


def test_a_scaled_byte_store_becomes_a_halfword_element():
    found = variants(SOURCE, 'f', '')
    assert [family for family, _ in found] == [FAMILY, FAMILY]
    assert found[0][1] == SOURCE.replace('extern char D_80100000[];', 'extern u16 D_80100000[];').replace(
        '*((M2C_FIELD(arg0, u8 *, 0x6E) * 2) + D_80100000)', 'D_80100000[M2C_FIELD(arg0, u8 *, 0x6E)]')
    assert 'extern s16 D_80100000[];' in found[1][1]


def test_a_word_table_and_the_table_written_first():
    source = 'extern u8 T[];\n\nvoid f(int i)\n{\n    *(T + (i * 4)) = *((i * 4) + T) + 1;\n}\n'
    assert variants(source, 'f', '') == [(FAMILY, 'extern s32 T[];\n\nvoid f(int i)\n{\n    T[i] = T[i] + 1;\n}\n')]


def test_other_uses_mixed_sizes_and_header_tables_are_left_alone():
    assert variants(SOURCE.replace('= 0;', '= 0;\n    g(D_80100000);'), 'f', '') == []
    assert variants(SOURCE.replace('= 0;', '= *((1 * 4) + D_80100000);'), 'f', '') == []
    assert variants(SOURCE.replace('(M2C_FIELD(arg0, u8 *, 0x6E) * 2)', '(a - b * 2)'), 'f', '') == []
    assert variants(SOURCE, 'f', 'extern char D_80100000[];') == []
