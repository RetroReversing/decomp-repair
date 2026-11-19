"""Case labels on the default arm for values the target's jump table spans."""
from decomprepair import switch_range_repairs as s

SOURCE = '''void f(u8 x) {
    switch (x) {
    default:
        a();
        return;
    case 2:
        b();
        return;
    case 8:
        c();
        break;
    }
}
'''
ASM = 'addiu      $v1, $v0, -0x1\nsltiu      $v0, $v1, 0x9\n'


def test_the_targets_range():
    (family, out), = s.variants(SOURCE, 'f', ASM)
    assert family == 'switch_range'
    assert '    case 1:\n    case 9:\n    default:\n' in out


def test_left_alone_when_the_range_already_matches():
    assert s.variants(SOURCE, 'f', 'addiu      $v1, $v0, -0x2\nsltiu      $v0, $v1, 0x7\n') == []
    assert s.variants(SOURCE.replace('    default:\n        a();\n        return;\n', ''), 'f', ASM) == []
