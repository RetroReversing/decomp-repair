"""shared_global_round on made-up code."""
from decomprepair.registry import declared
from decomprepair.shared_global_round import FAMILY, variants

DRAFT = '''extern u32 heapStart;

void carve(void) {
    s32 buffer;
    s32 table;

    buffer = ((u32) (heapStart + 0xF) >> 4) * 0x10;
    table = ((u32) (heapStart + 0x7D0F) >> 4) * 0x10;
    use(buffer, table);
}
'''


def test_the_buffer_holds_the_global_while_the_table_is_computed():
    [(family, child)] = variants(DRAFT, 'carve')
    assert family == FAMILY
    assert ('    buffer = heapStart;\n    table = ((u32) (buffer + 0x7D0F) >> 4) * 0x10;\n'
            '    buffer = ((u32) (buffer + 0xF) >> 4) * 0x10;\n') in child


def test_a_local_is_not_a_global():
    local = DRAFT.replace('extern u32 heapStart;\n\n', '').replace('    s32 table;', '    s32 table;\n    u32 heapStart;')
    assert variants(local, 'carve') == []


def test_it_is_registered():
    assert any(FAMILY in repair.families for repair in declared())
