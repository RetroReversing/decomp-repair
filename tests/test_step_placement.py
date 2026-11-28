from decomprepair import step_placement as repair

SOURCE = '''
void f(s32 kind) {
    u32 tex;

    tex = pick(kind);
    memSet(&scale, 0, 12);
    if (kind == 1) {
        scale = 1;
    } else {
        scale = 2;
    }
    tex--;
    d->w1 = &table->m[count++] + 1;
    use(tex);
}
'''


def _children(family, source=SOURCE):
    return [child for got, child in repair.variants(source, 'f') if got == family]


def test_a_step_moves_above_statements_that_never_name_it():
    children = _children('local_step_hoist')
    assert len(children) == 2
    assert 'tex--;\n    if (kind == 1) {' in children[0]
    assert 'tex = pick(kind);\n    tex--;\n    memSet(&scale, 0, 12);' in children[1]
    assert all(child.count('tex--;') == 1 for child in children)


def test_an_index_post_increment_becomes_a_following_statement():
    child = _children('index_postinc_statement')[0]
    assert 'd->w1 = &table->m[count] + 1;\n    count++;\n' in child


def test_an_argument_difference_is_stepped_before_the_call():
    source = SOURCE.replace('    tex--;\n', '').replace('use(tex);', 'use(tex - 1);')
    children = _children('local_step_hoist', source)
    assert any('tex -= 1;\n    if (kind == 1) {' in child and 'use(tex);' in child for child in children)


def test_a_value_read_after_the_call_is_not_stepped():
    source = SOURCE.replace('    tex--;\n', '').replace('use(tex);', 'use(tex - 1);\n    use(tex);')
    assert not _children('local_step_hoist', source)


def test_a_call_in_the_indexing_statement_is_left_alone():
    assert not _children('index_postinc_statement', SOURCE.replace('+ 1;\n    use', '+ g();\n    use'))


def test_the_families_are_declared():
    assert repair.REPAIR['families'] == ('local_step_hoist', 'index_postinc_statement')
