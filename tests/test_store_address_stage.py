from decomprepair import registry
from decomprepair.store_address_stage import FAMILY, REPAIR, left_associate, variants

SOURCE = """void bind(Entity *e, u8 *rec, s32 ch) {
    u8 key;
    void *row;
    key = rec[8];
    if (key != 0xFF) {
        row = (void *) ((key * 8) + e->bank);
        *((s32 *) (((char *) ((ch * 4) + e)) + 0xF80)) = (s32) (((*((u16 *) (((char *) row) + 0))) << 0x10) | (((*((u8 *) (((char *) row) + 2))) << 8) | (*((u8 *) (((char *) row) + 3)))));
    }
}
"""


def children(source=SOURCE):
    return [c for f, c in variants(source, 'bind') if f == FAMILY]


def test_the_address_is_staged_first_in_the_block():
    first = children()[0]
    assert first.index('store_address = (u8 *) ((ch * 4) + e);') < first.index('row = ')
    assert '*((s32 *) (store_address + 0xF80))' in first
    assert 'u8 *store_address;' in first


def test_the_second_child_also_associates_the_or_chain_to_the_left():
    second = children()[1]
    assert '(((*((u16 *) (((char *) row) + 0))) << 0x10) | ((*((u8 *) (((char *) row) + 2))) << 8))' in second
    assert second.index('<< 8))') < second.index('| (*((u8 *) (((char *) row) + 3)))')


def test_left_association():
    assert left_associate('(s32) ((a << 16) | ((b << 8) | c))') == '(s32) (((a << 16) | (b << 8)) | c)'
    assert left_associate('(s32) (a + b)') is None


def test_an_address_a_statement_above_assigns_is_left_alone():
    assert children(SOURCE.replace('        row = ', '        ch = 2;\n        row = ')) == []


def test_a_store_through_a_simple_address_is_left_alone():
    assert children(SOURCE.replace('((ch * 4) + e)', 'e')) == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants
    assert FAMILY in {family for entry in registry.declared() for family in entry.families}
