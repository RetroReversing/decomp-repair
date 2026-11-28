from decomprepair import compare_before_step

DRAFT = '''
void fade(void *arg0) {
    s32 temp_v0;
    u8 temp_s0;

    temp_s0 = *(u8 *)((s8 *)arg0 + 0x11);
    move();
    temp_v0 = temp_s0 - 1;
    *(s8 *)((s8 *)arg0 + 0x13) = (temp_s0 - 1);
    *(u8 *)((s8 *)arg0 + 0x11) = (u8) (temp_s0 - 1);
    if (((temp_s0 - 1) < 0x81) || (*(u8 *)((s8 *)arg0 + 0x16) != 0)) {
        release(arg0);
    }
}
'''


def _children(source):
    return [child for _, child in compare_before_step.variants(source, 'fade')]


def test_flag_step_and_widening_come_in_one_child():
    (child,) = _children(DRAFT)
    assert 'int temp_s0;\n    int temp_s0_before;' in child
    assert 'temp_s0 = (u8) (*(u8 *)((s8 *)arg0 + 0x11));' in child
    assert 'temp_s0_before = (temp_s0 - 1) < 0x81;\n    temp_s0--;\n    temp_v0 = temp_s0;' in child
    assert '= (u8) (temp_s0);' in child
    assert 'if ((temp_s0_before) || ' in child


def test_a_word_local_keeps_its_type_and_other_steps_are_written():
    child = _children(DRAFT.replace('u8 temp_s0;', 's32 temp_s0;').replace('temp_s0 - 1', 'temp_s0 + 4'))[0]
    assert 's32 temp_s0;\n    int temp_s0_before;' in child
    assert 'temp_s0 += 4;' in child and '(u8) (*(u8 *)' not in child


def test_refused_when_the_value_would_change():
    for changed in (
        DRAFT.replace('release(arg0);', 'release(temp_s0);'),            # another use of the loaded value
        DRAFT.replace('(s8 *)arg0 + 0x13) = (temp_s0 - 1)', '(s8 *)arg0 + 0x13) = (temp_s0 - 2)'),
        DRAFT.replace('release(arg0);', 'temp_s0 = 3;'),                 # assigned twice
        DRAFT.replace('move();', 'move(&temp_s0);'),
        DRAFT.replace('((temp_s0 - 1) < 0x81)', '((u32) (temp_s0 - 1) < 0x81)'),
        DRAFT.replace('    move();', '    do {\n    move();').replace('release(arg0);\n    }', 'release(arg0);\n    }\n    } while (0);'),
        DRAFT.replace('temp_v0 = temp_s0 - 1;', 'if (arg0) temp_v0 = 0; else temp_v0 = temp_s0 - 1;'),
    ):
        assert _children(changed) == []
