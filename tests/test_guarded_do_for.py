from decomprepair.guarded_do_for_repairs import variants

SOURCE = """void level(s32 start, u32 end) {
    u32 i;
    i = start;
    if (i < end) {
        do {
            visit(i);
            if (i == 3) {
                skip(i);
            }
            i++;
        } while (i < end);
    }
    done();
}
"""


def test_the_guard_and_do_while_become_a_for_loop():
    (family, candidate), = variants(SOURCE, 'level')
    assert family == 'guarded_do_for'
    assert 'for (; i < end; i++) {' in candidate
    assert 'do {' not in candidate and 'while' not in candidate
    assert 'visit(i);' in candidate and 'i++;\n' not in candidate.split('for')[1].split('}')[0]
    assert candidate.rstrip().endswith('done();\n}')


def test_other_steps_are_recognised():
    for step in ('++i;', 'i += 1;', 'i = i + 1;'):
        (_, candidate), = variants(SOURCE.replace('i++;', step), 'level')
        assert 'for (; i < end; i++)' in candidate


def test_refused_when_the_rewrite_would_change_the_loop():
    assert not variants(SOURCE.replace('while (i < end);', 'while (i < end + 1);'), 'level')  # another test
    assert not variants(SOURCE.replace('i++;', 'i += 2;'), 'level')  # not a step by one
    assert not variants(SOURCE.replace('skip(i);', 'continue;'), 'level')  # continue skips the step in the do
    assert not variants(SOURCE.replace('i++;\n', ''), 'level')  # no step at all
