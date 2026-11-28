"""Byte offsets with the stride in them off one object, written as a record array."""
from decomprepair.indexed_base_records import FAMILY, variants

SOURCE = """extern M2C_UNK gSlots;
typedef struct { s32 data[0x40]; } Block;

void load(void) {
    M2C_UNK sp0;
    M2C_UNK *p;
    M2C_UNK *q;
    Block table;
    u32 i;

    *(Block *)(&table) = *(Block *)(&D_ROM);
    p = &gSlots;
    q = &table;
    do {
        M2C_FIELD(p, s32 *, i * 0x10) = M2C_FIELD(q, s32 *, (i - 1) * 8 + 4);
        M2C_FIELD(p, s8 *, i * 0x10 + 0xC) = 0;
        i += 1;
    } while (i < 4U);
    M2C_FIELD(&gSlots, s8 *, 0x4C) = 1;
}
"""


def test_the_symbol_and_the_stack_table_become_record_arrays():
    children = variants(SOURCE, 'load')
    assert all(family == FAMILY for family, _ in children)
    text = children[0][1]
    assert 'extern __repair_row_gSlots gSlots[];' in text
    assert 'gSlots[i].m0 = table.e[i - 1].m4;' in text
    assert 'gSlots[i].mC = 0;' in text and 'gSlots[4].mC = 1;' in text
    assert 'typedef struct { __repair_row_table e[0x20]; } __repair_row_table_table;' in text
    assert 'p = &gSlots;' not in text and 'M2C_UNK *q;' not in text
    assert 'extern M2C_UNK gSlots;' not in text


def test_a_pointer_used_for_anything_else_is_left_alone():
    source = SOURCE.replace('    M2C_FIELD(&gSlots, s8 *, 0x4C) = 1;\n', '    use(p, q);\n')
    assert variants(source, 'load') == []
