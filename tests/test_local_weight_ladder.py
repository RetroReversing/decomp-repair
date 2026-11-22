import re

from decomprepair import local_weight_ladder
from decomprepair.local_weight_ladder import FAMILY, ladders, split_declarations, units, variants

SOURCE = """s32 take(HeapBlock *head, u32 size) {
    HeapBlock *block = head;
    if (block != NULL) {
        do {
            u32 avail = block->size;
            u8 *end = (u8 *)block + avail;
            if (avail >= size) {
                HeapBlock *rest;
                u32 used;
                avail = size + 12;
                used = gUsed;
                rest = (HeapBlock *)((u32)end - avail);
                gUsed = used + size;
                rest->prev = NULL;
                rest->size = avail;
                return (s32)(rest + 1);
            }
            block = block->next;
        } while (block != NULL);
    }
    return 0;
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def test_initialised_declarations_are_split_in_order_and_change_no_code():
    out = _flat(split_declarations(SOURCE, 'take'))
    assert 'u32 avail; u8 *end; if' not in out
    assert 'u32 avail; u8 *end; avail = block->size; end = (u8 *)block + avail; if (avail >= size)' in out
    assert 'HeapBlock *block; block = head;' in out
    assert split_declarations('void f(void) { u32 a; a = 1; g(a); }', 'f') == 'void f(void) { u32 a; a = 1; g(a); }'


def test_statements_name_the_locals_they_touch():
    found, tracked = units(split_declarations(SOURCE, 'take'), 'take')
    by_text = {_flat(text): counts for _, _, text, counts in found}
    assert by_text['avail = size + 12;'] == {'avail': 1, 'size': 1}
    assert {'avail', 'end', 'rest', 'block', 'size', 'head', 'used'} <= tracked


def test_the_ladder_of_one_local_against_a_rival_is_one_child():
    """The statements that name the first local and not the rival, three, one and three deep, with one later
    statement pinned: the shape that moved a block's size above the pointer carved from it."""
    flat = [_flat(text) for family, text in variants(SOURCE, 'take') if family == FAMILY]
    deep = lambda stmt, n: 'do { ' * n + stmt + ' } while (0);' * n
    wanted = (deep('avail = block->size;', 3), deep('end = (u8 *)block + avail;', 1), deep('avail = size + 12;', 3))
    assert any(all(piece in text for piece in wanted) and text.count('while (0)') == 3 + 1 + 3 + 1 for text in flat), len(flat)


def test_children_are_distinct_bounded_and_fewest_wrappers_first():
    found, _ = units(split_declarations(SOURCE, 'take'), 'take')
    shapes = ladders(found)
    assert shapes and all(total >= 1 for total, _ in shapes)
    assert [t for t, _ in shapes] == sorted(t for t, _ in shapes)
    children = variants(SOURCE, 'take')
    assert 0 < len(children) <= local_weight_ladder.LIMIT
    assert len({text for _, text in children}) == len(children)


def test_nothing_when_the_function_has_no_statements_naming_two_locals():
    assert variants('void f(void) { g(); h(); }', 'f') == []
    assert variants('void f(s32 a) { asm("nop"); g(a); h(a); }', 'f') == []
