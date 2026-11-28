"""A staged value on both paths of a nested guard, written as one `&&` condition."""
from decomprepair import guarded_stage_join, registry

SOURCE = """s32 pick(s32 arg0) {
    s32 var_v0;

    if (gReady != 0) {
        var_v0 = arg0 * 2;
        if (gLast == arg0) {
            return 0;
        }
        goto block_4;
    }
    var_v0 = arg0 * 2;
block_4:
    return var_v0 + arg0;
}
"""


def test_the_two_tests_become_one_condition():
    [(family, text)] = guarded_stage_join.variants(SOURCE, 'pick')
    assert family == 'guarded_stage_join'
    assert 'if ((gReady != 0) && (gLast == arg0)) {\n        return 0;\n    }\n    var_v0 = arg0 * 2;\n' in text
    assert 'goto' not in text and 'block_4' not in text


def test_a_label_another_goto_uses_stays():
    source = SOURCE.replace('    if (gReady != 0) {', '    if (arg0 < 0) {\n        goto block_4;\n    }\n    if (gReady != 0) {')
    [(_, text)] = guarded_stage_join.variants(source, 'pick')
    assert 'block_4:' in text


def test_declines_when_the_second_test_reads_the_staged_value_or_the_copies_differ():
    assert guarded_stage_join.variants(SOURCE.replace('gLast == arg0', 'gLast == var_v0'), 'pick') == []
    assert guarded_stage_join.variants(SOURCE.replace('    var_v0 = arg0 * 2;\nblock_4:', '    var_v0 = arg0;\nblock_4:'),
                                       'pick') == []


def test_it_is_registered():
    assert any(entry.module.endswith('guarded_stage_join') for entry in registry.declared())
