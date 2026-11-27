from decomprepair import counted_for_guarded_do, missing_call_argument_local, nested_exit_loop_ladder

LADDER = '''int pairHits(int a) {
    int var_s2;
    int var_s3;
    int var_v0;

    var_s3 = 0;
    for (;;) {
        var_v0 = 0;
        if (var_s3 < leftCount) {
            var_s2 = 0;
            if (rightCount != 0) {
                for (;;) {
                    var_v0 = 1;
                    if (hits(var_s3, var_s2) == 0) {
                        var_v0 = 1;
                        if (hits(var_s2, var_s3) == 0) {
                            var_s2 += 1;
                            if (var_s2 >= rightCount) {
                                goto block_7;
                            }
                            continue;
                        }
                    }
                    break;
                }
            } else {
block_7:
                var_s3 += 1;
                continue;
            }
        }
        break;
    }
    return var_v0;
}
'''


def test_ladder_becomes_a_do_while_with_returns():
    children = [text for _, text in nested_exit_loop_ladder.variants(LADDER, 'pairHits')]
    assert len(children) == 2
    joined, split = children
    for child in children:
        assert 'goto' not in child and 'block_7' not in child and 'var_v0' not in child
        assert '} while (var_s2 < rightCount);' in child
        assert child.rstrip().endswith('return 0;\n}')
        assert 'return 1;' in child
    assert 'if (hits(var_s3, var_s2) != 0 || hits(var_s2, var_s3) != 0) {' in joined
    assert split.count('return 1;') == 2


def test_ladder_keeps_a_result_that_is_not_only_literals():
    source = LADDER.replace('    return var_v0;', '    return var_v0 + a;')
    child = nested_exit_loop_ladder.variants(source, 'pairHits')
    assert child and all('return var_v0 + a;' in text for _, text in child)


def test_ladder_needs_the_label_in_the_else():
    assert not nested_exit_loop_ladder.variants(LADDER.replace('goto block_7;', 'break;'), 'pairHits')


def test_counted_for_becomes_a_guarded_do():
    source = 'void f(void) {\n    int j;\n    for (j = 0; j < count; j++) {\n        use(j);\n    }\n}\n'
    (_, child), = counted_for_guarded_do.variants(source, 'f')
    assert 'j = 0;\nif (j < count) {\ndo {' in child and 'j++;\n} while (j < count);' in child
    assert not counted_for_guarded_do.variants(source.replace('count;', 'size();'), 'f')
    assert not counted_for_guarded_do.variants(source.replace('use(j);', 'continue;'), 'f')


def test_call_short_of_an_argument_takes_the_variable_of_the_copied_register():
    source = ('int other();\nvoid f(void) {\n    void *temp_s0;\n    void *temp_s1;\n    temp_s0 = first;\n'
              '    temp_s1 = second;\n    other(temp_s0, temp_s1);\n    other(temp_s1);\n}\n')
    asm = ('addu $a0, $s0, $zero\njal other\naddu $a1, $s1, $zero\n'
           'addu $a0, $s1, $zero\njal other\naddu $a1, $s0, $zero\n')
    children = [text for _, text in missing_call_argument_local.variants(source, 'f', asm)]
    assert any('other(temp_s1, temp_s0);' in text for text in children)
