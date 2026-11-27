"""A byte offset added to a pointer to an unknown table symbol, read at the width the target loads."""
from decomprepair import registry
from decomprepair import word_table_pointer_sum as p

SOURCE = '''extern M2C_UNK D_80100000;

void spawn(s16 *out, s32 index)
{
    M2C_UNK *table;

    table = &D_80100000;
    out[0] = (s16) (*((index * 4) + table) >> 1);
    out[1] = (s16) (*(((index * 4) | 2) + table) >> 1);
}
'''
ASM = '''lui $v0, %hi(D_80100000)
addiu $s6, $v0, %lo(D_80100000)
sll $v0, $s0, 2
addu $v0, $v0, $s6
lhu $v1, 0x0($v0)
sll $v0, $s0, 2
ori $v0, $v0, 0x2
addu $v0, $v0, $s6
lhu $v1, 0x0($v0)
'''


def test_the_table_is_an_array_of_the_loaded_type_then_read_by_bytes():
    elements, bytes_ = [child for _, child in p.variants(SOURCE, 'spawn', ASM)]
    assert 'extern u16 D_80100000[];' in elements
    assert 'D_80100000[index * 2] >> 1' in elements and 'D_80100000[(index * 2) + 1] >> 1' in elements
    assert 'table' not in elements
    assert '*(u16 *) ((u8 *) table + (index * 4)) >> 1' in bytes_
    assert '*(u16 *) ((u8 *) table + ((index * 4) | 2)) >> 1' in bytes_


def test_the_address_written_in_the_sum_is_taken_too():
    source = SOURCE.replace('+ table)', '+ &D_80100000)').replace('    table = &D_80100000;\n', '')
    first = p.variants(source, 'spawn', ASM)[0][1]
    assert 'D_80100000[(index * 2) + 1]' in first


def test_another_use_of_the_pointer_keeps_the_declaration():
    source = SOURCE.replace('    out[0]', '    keep(table);\n    out[0]')
    children = [child for _, child in p.variants(source, 'spawn', ASM)]
    assert len(children) == 1 and 'extern M2C_UNK D_80100000;' in children[0]


def test_stores_word_loads_and_element_offsets_are_left_alone():
    assert p.variants(SOURCE, 'spawn', ASM.replace('lhu', 'lw')) == []
    assert p.variants(SOURCE.replace('index * 4) + table', 'index) + table').replace('((index * 4) | 2)', '(index)'),
                      'spawn', ASM) == []
    store = SOURCE.replace('out[1] = (s16) (*(((index * 4) | 2) + table) >> 1);', '*((index * 4) + table) = 0;')
    assert all('*((index * 4) + table) = 0;' in child for _, child in p.variants(store, 'spawn', ASM))


def test_it_is_declared_for_every_lane():
    assert registry.problems(registry.get('word_table_pointer_sum')) == []
