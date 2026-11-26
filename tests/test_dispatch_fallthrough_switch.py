from decomprepair import dispatch_fallthrough_switch as m

SOURCE = '''void f(s32 arg0) {
    s16 var_v0;
    u16 temp_v1;

    temp_v1 = state[arg0];
    if (temp_v1 != 1) {
        if ((s32) temp_v1 >= 2) {
            if (temp_v1 != 2) {
                return;
            }
            if (count > 0) {
                count = count - 1;
            } else {
                var_v0 = 1;
                goto block_15;
            }
            goto block_16;
        }
        if (temp_v1 != 0) {
            return;
        }
        reset(1);
        return;
    }
    if (count < 0xA0) {
        count = count + 1;
    } else {
        var_v0 = 2;
block_15:
        state[arg0] = var_v0;
    }
block_16:
    publish(count);
}
'''


def test_the_fallen_into_code_is_a_case_and_the_shared_tail_follows_the_switch():
    children = [source for _, source in m.variants(SOURCE, 'f')]
    assert len(children) == 2
    inlined, kept = children
    assert 'goto' not in inlined and 'block_1' not in inlined
    cases = inlined[inlined.index('switch (temp_v1) {'):inlined.index('publish(count);')]
    assert cases.index('case 0:') < cases.index('case 1:') < cases.index('case 2:') < cases.index('default:')
    assert 'reset(1);\n        return;' in cases
    assert 'var_v0 = 1;\n            state[arg0] = var_v0; break;' in cases  # the label's run, written out
    assert cases.rstrip().endswith('return;\n    }')
    assert 'goto block_15;' in kept and 'goto block_16;' in kept and 'block_16:' in kept


def test_an_if_else_is_left_alone():
    source = 'void f(s32 a) {\n    if (a != 1) {\n        g();\n        return;\n    }\n    h();\n}\n'
    assert m.variants(source, 'f') == []


def test_a_goto_out_of_a_loop_is_not_written_as_break():
    source = SOURCE.replace('var_v0 = 1;\n                goto block_15;',
                            'while (count) { goto block_16; }')
    assert [s for _, s in m.variants(source, 'f') if 'goto' not in s] == []
