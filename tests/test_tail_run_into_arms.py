"""A case's tail after an if/else written into each arm (an N64 audio thread, SN64 GCC 2.8.1, 26300 -> 25060)."""
from decomprepair.tail_run_into_arms import FAMILY, variants

SOURCE = """void thread(void)
{
    s32 arg;

    for (;;) {
        arg = next();
        switch (arg) {
        case 3:
            if (arg == cur) {
                if (handle != 0) {
                    break;
                }
            } else {
                play(arg, bank);
                cur = arg;
            }
            handle = start(bank);
            setvol(handle, vol);
            break;
        }
    }
}
"""


def test_the_tail_goes_into_each_arm_longest_first():
    found = variants(SOURCE, 'thread')
    assert [family for family, _ in found] == [FAMILY, FAMILY]
    both = found[0][1]
    assert ('                if (handle != 0) {\n                    break;\n                }\n'
            '                handle = start(bank);\n                setvol(handle, vol);\n            } else {\n') in both
    assert ('                cur = arg;\n                handle = start(bank);\n                setvol(handle, vol);\n'
            '            }\n            break;\n') in both
    one = found[1][1]
    assert '            }\n            setvol(handle, vol);\n            break;\n' in one


def test_an_arm_that_exits_is_left_alone_and_no_chain_means_no_child():
    exiting = SOURCE.replace('                cur = arg;\n', '                cur = arg;\n                return;\n')
    text = variants(exiting, 'thread')[0][1]
    assert 'return;\n            }\n            break;' in text
    assert variants(SOURCE.replace('} else {', '}\n            {'), 'thread') == []
