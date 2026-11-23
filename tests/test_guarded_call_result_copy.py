"""A call's pointer result copied into a second local inside the non-null guard (a player update, 2451 -> 2321)."""
from decomprepair.guarded_call_result_copy import FAMILY, REPAIR, variants

SOURCE = """void spawn(Slot *slot)
{
    void *item;
    s32 n;
    item = alloc_item();
    slot->item = item;
    if (item != NULL) {
        item->kind = 3;
        init(item, n);
        item->flags = 1;
    }
}
"""


def children(source):
    return [text for family, text in variants(source, 'spawn') if family == FAMILY]


def test_the_guard_copies_the_result_and_reads_the_copy():
    found = children(SOURCE)
    assert len(found) == 1
    child = found[0]
    assert '    void *item_copy;\n' in child
    assert 'if (item != NULL) {\n      item_copy = item;\n' in child or 'if (item != NULL) {\n        item_copy = item;\n' in child
    assert 'item_copy->kind = 3;' in child and 'init(item_copy, n);' in child and 'item_copy->flags = 1;' in child
    assert 'slot->item = item;' in child


def test_the_other_guard_spellings_count():
    assert len(children(SOURCE.replace('if (item != NULL)', 'if (item)'))) == 1
    assert len(children(SOURCE.replace('if (item != NULL)', 'if (item != 0)'))) == 1


def test_a_body_that_writes_or_addresses_the_pointer_is_left_alone():
    assert children(SOURCE.replace('item->flags = 1;', 'item = next(item);')) == []
    assert children(SOURCE.replace('item->flags = 1;', 'take(&item);')) == []


def test_a_guard_with_one_mention_or_a_block_between_is_left_alone():
    assert children(SOURCE.replace('        item->kind = 3;\n        init(item, n);\n', '        init(item, n);\n').replace('        item->flags = 1;\n', '')) == []
    assert children(SOURCE.replace('    slot->item = item;\n', '    if (n) {\n        slot->item = item;\n    }\n')) == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and FAMILY in REPAIR['families']
