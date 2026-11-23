from decomprepair import registry
from decomprepair.global_read_store_copy import FAMILY, REPAIR, variants

SOURCE = """s32 next_id(Table *t) {
    s32 id;
    s32 count;
    do {
        count = 0;
        id = gNextId;
        gNextId = (id + 1) & 0x7FFFFFFF;
        while (count < 8) {
            if (t->entry[count].id == id) {
                id = -1;
            }
            count += 1;
        }
    } while (id == -1);
    return id;
}
"""


def children(source=SOURCE):
    return [c for f, c in variants(source, 'next_id') if f == FAMILY]


def test_the_read_goes_to_a_temporary_and_the_local_is_copied_after_the_store():
    got = children()
    assert len(got) == 1
    child = got[0]
    assert 's32 id_read;' in child
    assert child.index('id_read = gNextId;') < child.index('gNextId = (id_read + 1) & 0x7FFFFFFF;') < child.index('id = id_read;')


def test_a_local_assigned_once_is_left_alone():
    assert children(SOURCE.replace('                id = -1;\n', '                count = 9;\n')) == []


def test_a_global_the_function_declares_is_not_a_global():
    assert children(SOURCE.replace('    s32 count;\n', '    s32 count;\n    s32 gNextId;\n')) == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants
    assert FAMILY in {family for entry in registry.declared() for family in entry.families}
