from decomprepair.postincrement_after_test import FAMILY, variants

SOURCE = """void walk(s32 *cursor, s32 index, s32 limit) {
    s32 temp;
    s32 rank;
    temp = 0;
    rank = 0;
    do {
        if ((temp++) != index) {
            rank += *cursor;
        }
        cursor++;
    } while (temp < limit);
    use(rank);
}
"""


def _children(source=SOURCE):
    return [child for family, child in variants(source, 'walk') if family == FAMILY]


def test_the_increment_moves_after_the_if_and_the_test_reads_the_counter():
    children = _children()
    assert len(children) == 1
    child = children[0]
    assert 'if (temp != index) {' in child
    assert child.index('rank += *cursor;') < child.index('temp++;') < child.index('cursor++;')
    assert '(temp++)' not in child


def test_the_mirrored_test_and_the_else_arm_are_handled():
    mirrored = SOURCE.replace('(temp++) != index', 'index < temp++')
    assert 'if (index < temp) {' in _children(mirrored)[0]
    with_else = SOURCE.replace('            rank += *cursor;\n        }', '            rank += *cursor;\n        } else {\n            rank = 0;\n        }')
    child = _children(with_else)[0]
    assert child.index('rank = 0;') < child.index('temp++;')


def test_an_arm_that_reads_the_counter_or_leaves_the_block_is_left_alone():
    assert _children(SOURCE.replace('rank += *cursor;', 'rank += temp;')) == []
    assert _children(SOURCE.replace('rank += *cursor;', 'if (rank) break;')) == []


def test_an_else_if_is_left_alone_because_the_increment_would_run_on_other_paths():
    chained = SOURCE.replace('        if ((temp++) != index) {', '        if (rank) {\n            rank--;\n        } else if ((temp++) != index) {')
    assert _children(chained) == []


def test_a_condition_that_reads_the_counter_again_or_has_side_effects_is_left_alone():
    assert _children(SOURCE.replace('(temp++) != index', 'temp++ != temp')) == []
    assert _children(SOURCE.replace('(temp++) != index', 'temp++ != index++')) == []
