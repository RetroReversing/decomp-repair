"""m2c's nested if tree over one variable, as a switch."""
from decomprepair import if_tree_switch_repairs as t

SOURCE = '''s32 f(s32 arg0, s32 arg1) {
    s32 temp_a0;

    temp_a0 = arg0 & 0xFFFF;
    if (temp_a0 != 0x2000) {
        if (temp_a0 >= 0x2001) {
            if (temp_a0 != 0x8000) {
                return 1;
            }
            D->x = 0;
            return 1;
        }
        if (temp_a0 != 0) {
            return 1;
        }
        g(D2);
        return 0x2001;
    }
    h(arg1 & 0xFF);
    if (D3 == 1) {
        D4 = 1;
    }
    return 0x8001;
}
'''


def test_the_tree_becomes_a_switch():
    # An N64 function at 76.4%: exact as `switch (arg0 & 0xFFFF)` with cases 0, 0x2000, 0x8000 in that order.
    out = [text for _, text in t.variants(SOURCE, 'f')]
    inline = [o for o in out if 'switch (arg0 & 0xFFFF)' in o][0]
    assert 'temp_a0' not in inline
    assert inline.index('case 0:') < inline.index('case 0x2000:') < inline.index('case 0x8000:')
    assert 'if (D3 == 1)' in inline and inline.rstrip().endswith('return 1;\n}'.strip())
    assert any('switch (temp_a0)' in o for o in out)


def test_left_alone_otherwise():
    def none(source):
        return t.variants(source, 'f') == []
    assert none(SOURCE.replace('if (temp_a0 >= 0x2001)', 'if (arg1 >= 0x2001)'))  # two variables tested
    assert none(SOURCE.replace('        g(D2);\n', '        goto end;\n'))  # a goto
    assert none(SOURCE.replace('    h(arg1 & 0xFF);\n', '    temp_a0 = 5;\n'))  # the variable changes
    # a range, not single values: values below 0x2000 return 1 or call g, so the ranges disagree
    assert none(SOURCE.replace('if (temp_a0 != 0) {', 'if (temp_a0 >= 0x10) {'))


def test_propose_finds_it():
    from decomprepair.propose import propose
    assert any(p.module == 'if_tree_switch_repairs' for p in propose(SOURCE, 'f').proposals)
