"""A cursor's step after the reads of its operands moved before them, the reads rebased."""
from decomprepair import cursor_advance_first as m

SOURCE = '''Gfx *f(u8 *cmd, Gfx *gfx)
{
    u32 c;
    s32 n;
    for (;;) {
        switch (*cmd) {
        case 2:
            {
                Gfx *_g = gfx++;
                n = cmd[1];
                c = (cmd[2] << 24) | cmd[5];
                _g->w0 = (n << 1) | 0x02100000;
                _g->w1 = c;
            }
            cmd += 6;
            break;
        case 3:
            if (D_80140300) {
                g(*cmd);
            }
            cmd = cmd + 2;
            break;
        default:
            return gfx;
        }
    }
}
'''


def test_step_moved_to_the_head_of_its_arm():
    # An SN GCC 2.8.1 model loader's second gSPModifyVertex arm: 1480 -> 1335 with the step first (the loads read at
    # -6($s1) after the giv increments, as in the target).
    (family, last), (_, first), (_, both) = m.variants(SOURCE, 'f')
    assert family == 'cursor_advance_first'
    assert 'case 3:\n            cmd = cmd + 2;' not in last
    assert 'case 3:\n            cmd += 2;\n            if (D_80140300) {\n                g(cmd[-2]);' in last
    assert 'case 2:\n            {' in last and 'cmd += 6;\n            break;' in last
    assert ('case 2:\n            cmd += 6;\n            {\n                Gfx *_g = gfx++;\n                n = cmd[-5];\n'
            '                c = (cmd[-4] << 24) | cmd[-1];') in first
    assert '            }\n            break;\n        case 3:' in first and 'g(*cmd);' in first
    assert 'n = cmd[-5];' in both and 'g(cmd[-2]);' in both


def test_left_alone_otherwise():
    # a use that isn't a constant index, a jump in the run, the cursor assigned in it, its address taken
    assert m.variants(SOURCE.replace('n = cmd[1];', 'n = cmd[n];').replace('g(*cmd);', 'g(cmd);'), 'f') == []
    assert m.variants(SOURCE.replace('g(*cmd);', 'g(cmd + 1);').replace('_g->w1 = c;', '_g->w1 = c; if (c) break;'),
                      'f') == []
    assert m.variants(SOURCE.replace('g(*cmd);', 'cmd++;').replace('n = cmd[1];', 'n = *cmd++;'), 'f') == []
    assert m.variants(SOURCE.replace('return gfx;', 'h(&cmd); return gfx;'), 'f') == []
    assert m.variants('void f(s32 *p)\n{\n    s32 n;\n    n = p[1];\n    n += 2;\n}\n', 'f') == []
