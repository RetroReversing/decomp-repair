from decomprepair.switch_weight_ladder import variants

SOURCE = '''
void f(int key) {
    switch (key) {
    case 1: call(1); break;
    case 2: call(2); break;
    default: break;
    }
    done();
}
'''


def test_weights_the_whole_switch_without_moving_its_breaks():
    children = variants(SOURCE, 'f')
    assert len(children) == 7
    assert children[4][1].count('do {') == 6
    assert 'case 1: call(1); break;' in children[4][1]
    assert 'done();' in children[4][1]


def test_excludes_continue_and_jumps_into_or_out_of_switch():
    assert not variants(SOURCE.replace('call(1); break;', 'continue;'), 'f')
    assert not variants(SOURCE.replace('call(1); break;', 'goto other;'), 'f')
    assert not variants(SOURCE.replace('    switch (key)', '    goto label;\n    switch (key)'), 'f')
    assert not variants(SOURCE.replace('call(1); break;', '__asm__("nop"); break;'), 'f')
