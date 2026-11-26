"""A loop counter that shares its variable with unrelated values given a variable of its own."""
from decomprepair import loop_counter_own as m

SOURCE = '''void f(Part *parts, s32 n, u8 *cmd)
{
    s32 i;
    s32 kt;
    for (i = 0; i < n; i++) {
        for (kt = 0; kt < parts[i].n; kt++) {
        }
    }
    for (;;) {
        switch (*cmd) {
        case 4:
            kt = cmd[1] >> 5;
            g(kt);
            break;
        default:
            return;
        }
    }
}
'''


def test_loop_gets_its_own_counter():
    # An SN GCC 2.8.1 model loader's empty parts loop: 470 -> 410 with a counter of its own.
    (family, text), = m.variants(SOURCE, 'f')
    assert family == 'loop_counter_own'
    assert '    s32 kt;\n    s32 kt_loop;\n' in text
    assert 'for (kt_loop = 0; kt_loop < parts[i].n; kt_loop++) {' in text
    assert 'kt = cmd[1] >> 5;\n            g(kt);' in text


def test_left_alone_otherwise():
    # read after the loop before a set, read before the loop, address taken, nowhere else
    assert m.variants(SOURCE.replace('kt = cmd[1] >> 5;\n', ''), 'f') == []
    assert m.variants(SOURCE.replace('kt = cmd[1] >> 5;', 'kt = kt >> 5;'), 'f') == []
    assert m.variants(SOURCE.replace('    for (i = 0; i < n; i++) {\n', '    g(kt);\n    for (i = 0; i < n; i++) {\n'),
                      'f') == []
    assert m.variants(SOURCE.replace('g(kt);', 'g(&kt);'), 'f') == []
    assert m.variants(SOURCE.replace('kt = cmd[1] >> 5;\n            g(kt);', 'g(1);'), 'f') == []
