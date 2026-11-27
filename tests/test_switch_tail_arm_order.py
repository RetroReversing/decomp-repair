from decomprepair import switch_tail_arm_order as tails

SOURCE = '''void f(s32 v) {
    switch (v) {
    case 0:
        a();
        return;
    case 1:
        b();
        break;
    case 2:
        c();
        return;
    case 3:
        d();
        break;
    default:
        return;
    }
    G += 1;
}
'''


def test_the_tail_goes_into_the_breaking_arms_and_the_arms_reorder():
    out = [text for _, text in tails.variants(SOURCE, 'f')]
    assert 'b();\n        G += 1;\n        break;' in out[0] and 'd();\n        G += 1;\n        break;' in out[0]
    assert out[0].count('G += 1;') == 2 and out[0].endswith('return;\n    }\n}\n')
    assert len(out) == 24
    wanted = out[0]
    two = wanted[wanted.index('    case 2:'):wanted.index('    case 3:')]
    three = wanted[wanted.index('    case 3:'):wanted.index('    default:')]
    assert wanted.replace(two + three, three + two) in out


def test_declines_without_a_default_or_with_an_inner_break():
    assert tails.variants(SOURCE.replace('    default:\n        return;\n', ''), 'f') == []
    assert tails.variants(SOURCE.replace('        b();\n', '        if (b()) {\n            break;\n        }\n'), 'f') == []
    assert tails.variants(SOURCE.replace('void f', 's32 f'), 'f') == []
