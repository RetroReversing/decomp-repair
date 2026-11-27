from decomprepair import tail_return_inline as repair
from decomprepair.pattern_repairs import negate

SOURCE = '''f64 sample(f64 arg0, f64 arg1) {
    f64 value;
    f64 result;

    value = arg0 / arg1;
    result = value;
    if (arg1 > 0.0) {
        /* Duplicate return node */
        return result;
    }
    if (!(arg0 > 0.0)) {
        return value - 2.0;
    }
    result = value + 3.0;
    /* Duplicate return node */
    return result;
}
'''


def squash(text):
    return ' '.join(text.split())


def test_result_local_exits_are_returned_directly_and_the_last_two_exchanged():
    children = dict(repair.variants(SOURCE, 'sample'))
    plain = squash(children[repair.FAMILY])
    assert 'if (arg1 > 0.0) { /* Duplicate return node */ return value; }' in plain
    assert 'if (!(arg0 > 0.0)) { return value - 2.0; } return value + 3.0; }' in plain
    assert 'result =' not in plain
    flipped = squash(children[repair.FLIPPED])
    assert 'if (arg0 > 0.0) { return value + 3.0; } return value - 2.0; }' in flipped


def test_a_result_read_later_or_of_another_type_is_left_alone():
    read = SOURCE.replace('    if (!(arg0 > 0.0)) {', '    use(result);\n    if (!(arg0 > 0.0)) {')
    assert 'result = value;' in dict(repair.variants(read, 'sample'))[repair.FAMILY]
    narrow = SOURCE.replace('    f64 result;', '    f32 result;')
    assert repair.variants(narrow, 'sample') == []
    # set again on one path only: the other still reads the first value
    one_path = SOURCE.replace('    result = value + 3.0;', '    if (arg1 > 1.0) {\n        result = 1.0;\n    }')
    assert repair.variants(one_path, 'sample') == []
    jumped = SOURCE.replace('    value = arg0 / arg1;', '    value = arg0 / arg1;\nagain:\n    if (value > 9.0) {\n        goto again;\n    }')
    assert 'result = value;' in dict(repair.variants(jumped, 'sample'))[repair.FAMILY]
    tested = SOURCE.replace('if (arg1 > 0.0)', 'if (result > 0.0)')
    assert 'result = value;' in dict(repair.variants(tested, 'sample'))[repair.FAMILY]


def test_a_loop_before_the_exits_does_not_stop_the_rewrite():
    looped = SOURCE.replace('    value = arg0 / arg1;', '    value = arg0 / arg1;\n    do {\n        value -= 1.0;\n    } while (value > 9.0);')
    assert 'result =' not in dict(repair.variants(looped, 'sample'))[repair.FAMILY]


def test_a_negated_group_is_inverted_by_dropping_the_not():
    # `a > b` is not the opposite of `a <= b` for a NaN, so only the `!` is removed
    assert negate('!(fabs(x) <= 1.0)') == 'fabs(x) <= 1.0'
    assert negate('!(a && b)') == 'a && b'
    assert negate('!(a) == !(b)') == '!(a) != !(b)'
    assert negate('ready') is None
