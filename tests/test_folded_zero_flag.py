from decomprepair import folded_zero_flag as flags

SOURCE = '''void f(s32 v) {
    switch (v) {
    case 1:
        if (G == 0x10E) {
            g(2);
        }
        if ((G >= 0x186) || (0 & 0x10)) {
            g(1);
        }
        break;
    }
}
'''


def test_the_folded_zero_becomes_a_local_set_before_the_test():
    earlier, direct, head = [text for _, text in flags.variants(SOURCE, 'f')]
    assert 's32 zero_flag;' in earlier and '(zero_flag & 0x10)' in earlier
    assert 'case 1:\n        zero_flag = 0;\n        if (G == 0x10E)' in earlier
    assert 'zero_flag = 0;\n        if ((G >= 0x186)' in direct
    assert 's32 zero_flag;\n    zero_flag = 0;\n    switch' in head


def test_no_zero_mask_no_variants():
    assert flags.variants('void f(s32 v) { if (v & 0x10) g(); }', 'f') == []
