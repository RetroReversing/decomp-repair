from decomprepair import branch_value_run_sink as repair
from decomprepair import registry

SOURCE = '''
extern volatile Chan *volatile gChan;
void set_levels(u32 a, u32 b) {
short high = 0x300;
    s32 x;
    s16 y;

    if (a == 2) {
        x = high;
    } else {
        x = 0x200;
    }
    gChan->level = x;
    gChan->level = x;
    gChan->pan = 5;
    if (b == 2) {
        y = high;
        gChan->level = y;
    } else {
        y = 0x200;
        gChan->level = y;
    }
    gChan->level = y;
    gChan->pan = 6;
}
'''


def test_every_diamond_takes_its_run_in_one_child():
    family, text = repair.variants(SOURCE, 'set_levels')[0]
    assert family == 'branch_value_run_sink'
    assert '''    if (a == 2) {
        gChan->level = 0x300;
        gChan->level = 0x300;
    } else {
        gChan->level = 0x200;
        gChan->level = 0x200;
    }
    gChan->pan = 5;''' in text
    assert '''    if (b == 2) {
        gChan->level = 0x300;
        gChan->level = 0x300;
    } else {
        gChan->level = 0x200;
        gChan->level = 0x200;
    }
    gChan->pan = 6;''' in text


def test_a_value_read_later_keeps_its_assignment():
    source = SOURCE.replace('    gChan->pan = 5;\n', '    gChan->pan = 5;\n    gChan->aux = x;\n')
    texts = [text for _, text in repair.variants(source, 'set_levels')]
    assert any('x = high;\n        gChan->level = x;' in text for text in texts)
    assert not any('gChan->level = 0x300;\n        gChan->level = 0x300;\n    } else {\n        gChan->level = 0x200;\n'
                   '        gChan->level = 0x200;\n    }\n    gChan->pan = 5;' in text for text in texts)


def test_arms_with_control_flow_and_runs_that_write_the_value_stay():
    assert not repair.variants('''void f(s32 a) {
    s32 x;
    if (a) {
        x = 1;
        return;
    } else {
        x = 2;
    }
    g = x;
    h = x;
}''', 'f')
    assert not repair.variants('''void f(s32 a) {
    s32 x;
    if (a) {
        x = 1;
    } else {
        x = 2;
    }
    x += 1;
}''', 'f')


def test_it_declares_itself():
    entry = registry.get('branch_value_run_sink')
    assert entry and not registry.problems(entry)
