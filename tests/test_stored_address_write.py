"""A symbol written through the pointer just stored (an object setup routine's last row, 250 -> 0)."""
from decomprepair import registry
from decomprepair.stored_address_write import FAMILY, variants

SOURCE = """extern s8 D_801D59B2;
void setup(s32 id) {
    slots[id].data = &D_801D59B2;
    D_801D59B2 = 0;
}
"""


def test_the_write_goes_through_the_stored_pointer():
    (family, child), = variants(SOURCE, 'setup', '')
    assert family == FAMILY
    assert '*(s8 *) slots[id].data = 0;' in child and 'slots[id].data = &D_801D59B2;' in child


def test_the_type_can_come_from_the_header():
    source = SOURCE.replace('extern s8 D_801D59B2;\n', '')
    assert not variants(source, 'setup', '')
    assert variants(source, 'setup', 'extern u16 D_801D59B2;')


def test_only_an_adjacent_write_of_the_same_symbol():
    assert not variants(SOURCE.replace('    D_801D59B2 = 0;', '    other();\n    D_801D59B2 = 0;'), 'setup', '')
    assert not variants(SOURCE.replace('D_801D59B2 = 0;', 'D_801D59B2 == 0;'), 'setup', '')


def test_it_declares_itself():
    assert any(FAMILY in r.families for r in registry.declared())
