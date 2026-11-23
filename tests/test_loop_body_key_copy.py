from decomprepair.loop_body_key_copy import FAMILY, variants

SOURCE = """void rank(s32 slot) {
    volatile s32 *count = &gCount;
    short index = (s16) slot;
    s32 temp;
    s32 rank;
    s32 limit;
    temp = 0;
    rank = 0;
    do {
        limit = gBound;
        if (temp != index) {
            rank += table[temp];
        }
        temp++;
    } while (temp < limit);
    use(rank, index);
}
"""


def _children(source=SOURCE):
    return [child for family, child in variants(source, 'rank') if family == FAMILY]


def test_the_copy_is_the_first_statement_of_the_body_and_the_body_reads_it():
    children = _children()
    assert len(children) == 1
    child = children[0]
    assert 's32 index_copy;' in child
    assert child.index('s32 index_copy;') < child.index('temp = 0;')
    assert child.index('do {') < child.index('index_copy = index;') < child.index('limit = gBound;')
    assert 'if (temp != index_copy)' in child
    assert 'use(rank, index);' in child  # what follows the loop keeps the variable


def test_a_local_the_loop_writes_or_that_is_not_narrow_gets_no_copy():
    assert _children(SOURCE.replace('temp++;', 'temp++;\n        index = temp;')) == []
    assert _children(SOURCE.replace('short index', 's32 index')) == []


def test_a_loop_with_a_label_or_a_volatile_read_or_a_taken_address_is_left_alone():
    assert _children(SOURCE.replace('limit = gBound;', 'limit = *count;')) != []  # a pointer to volatile elsewhere is fine
    assert _children(SOURCE.replace('limit = gBound;', 'goto done;\n        done:\n        limit = gBound;')) == []
    assert _children(SOURCE.replace('rank += table[temp];', 'rank += f(&index);')) == []


def test_a_loop_whose_body_does_not_read_the_local_gets_no_copy():
    assert _children(SOURCE.replace('if (temp != index)', 'if (temp != 3)')) == []
