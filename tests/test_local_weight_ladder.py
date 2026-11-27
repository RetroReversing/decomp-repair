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


def test_bounded_ranking_keeps_exactly_the_first_full_ranking():
    found, _ = units(split_declarations(SOURCE, 'take'), 'take')
    all_shapes = ladders(found)
    for limit in (1, 10, 100, 500):
        assert ladders(found, limit) == all_shapes[:limit]


def test_many_locals_keep_only_the_requested_shapes():
    # The old implementation materialised every ranked pick before variants discarded all but 500.
    found = [(i, i + 1, '', {f'v{j}': 1 for j in (i % 20, (i + 1) % 20)}) for i in range(100)]
    shapes = ladders(found, 25)
    assert len(shapes) == 25
    assert shapes == sorted(shapes, key=lambda pair: (pair[0], len(pair[1]), tuple(sorted(pair[1].items()))))


def test_bounded_ranking_matches_exhaustive_reference():
    import random

    def reference(found):
        names = {n for _, _, _, counts in found for n in counts}
        shapes = set()
        for v in names:
            for w in names - {v}:
                if not any(v in counts and w in counts for _, _, _, counts in found):
                    continue
                indexes = [i for i, (_, _, _, counts) in enumerate(found) if v in counts and w not in counts]
                if not indexes:
                    continue
                for depth in (1, 2, 3):
                    choices = [({i: depth for i in indexes}, False)]
                    if depth > 1 and len(indexes) > 1:
                        for light in indexes:
                            choices.append(({**{i: depth for i in indexes}, light: depth - 1}, False))
                            if depth == 3:
                                choices.append(({**{i: depth for i in indexes}, light: 1}, True))
                    for shape, pinned in choices:
                        pins = [None] + ([p for p in range(len(found)) if p not in shape
                                          and any(0 < p - i <= 4 for i in shape)] if pinned else [])
                        for pin in pins:
                            picks = shape if pin is None else {**shape, pin: 1}
                            key = tuple(sorted(picks.items()))
                            shapes.add((sum(picks.values()), len(picks), key))
        return [(total, dict(key)) for total, _, key in sorted(shapes)]

    rng = random.Random(9)
    for _ in range(25):
        found = [(i, i + 1, '', {f'v{j}': 1 for j in range(5) if rng.randrange(3) == 0}) for i in range(8)]
        expected = reference(found)
        assert ladders(found) == expected
        for limit in (1, 5, 30):
            assert ladders(found, limit) == expected[:limit]
