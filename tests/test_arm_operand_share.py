"""Byte reads of a word two arms assemble the same way, held in locals both arms assign."""
from decomprepair import arm_operand_share as m

SOURCE = '''Gfx *f(u8 *cmd, Gfx *gfx)
{
    Gfx *dl;
    s32 n;
    u32 c;
    for (;;) {
        switch (*cmd) {
        case 2:
            {
                dl = gfx++;
                n = cmd[1];
                c = (cmd[2] << 24) | (cmd[3] << 16) | (cmd[4] << 8) | cmd[5];
                dl->w0 = (n << 1) | 0x02100000;
                dl->w1 = c;
            }
            cmd += 6;
            break;
        case 3:
            cmd += 6;
            {
                dl = gfx++;
                c = (cmd[-4] << 24) | (cmd[-3] << 16) | (cmd[-2] << 8) | cmd[-1];
                n = cmd[-5];
                dl->w0 = (n << 1) | 0x02140000;
                dl->w1 = c;
            }
            break;
        case 4:
            if (n) {
                n = 0;
                dl = gfx++;
                if (c) {
                    dl->w0 = 5;
                }
            }
            break;
        default:
            return gfx;
        }
    }
}
'''


def test_the_arms_bytes_shared_with_block_pointers_and_one_order():
    # An SN GCC 2.8.1 model loader's two gSPModifyVertex arms: 365 -> 0 in one step (the arm-order child with block
    # pointers); the byte locals alone 315 -> 100 under -mfp32.
    found = dict((family, text) for family, text in reversed(m.variants(SOURCE, 'f', 'typedef int s32;')))
    assert set(found) == set(m.FAMILIES)
    shared = found['arm_operand_share']
    assert shared.startswith('Gfx *f(u8 *cmd, Gfx *gfx)\n{\n    s32 c0, c1, c2, c3;\n    Gfx *dl;')
    assert ('                c0 = cmd[2];\n                c1 = cmd[3];\n                c2 = cmd[4];\n'
            '                c3 = cmd[5];\n                c = (c0 << 24) | (c1 << 16) | (c2 << 8) | c3;') in shared
    assert 'c0 = cmd[-4];' in shared and 'c3 = cmd[-1];' in shared and 'Gfx *dl = gfx++;' not in shared
    exact = m.variants(SOURCE, 'f', 'typedef int s32;')[2]
    assert exact[0] == 'arm_operand_share_arm_order'
    text = exact[1]
    assert text.count('Gfx *dl = gfx++;') == 2 and '                n = 0;\n                dl = gfx++;' in text
    assert ('                Gfx *dl = gfx++;\n                n = cmd[-5];\n                c0 = cmd[-4];') in text
    assert text.count('n = cmd[-5];') == 1


def test_pointer_left_shared_when_a_value_could_leave_its_block():
    leaky = SOURCE.replace('                if (c) {\n                    dl->w0 = 5;\n                }\n',
                           '').replace('            break;\n        default:', '            dl->w1 = 1;\n            break;\n'
                                       '        default:', 1)
    families = [family for family, _ in m.variants(leaky, 'f')]
    assert 'arm_operand_share' in families and 'arm_operand_share_block_pointer' not in families


def test_left_alone_otherwise():
    # one site only; reads that are not constant-index elements; a call in the word
    one = SOURCE.replace('c = (cmd[-4] << 24) | (cmd[-3] << 16) | (cmd[-2] << 8) | cmd[-1];', 'c = 0;')
    assert m.variants(one, 'f') == []
    loads = SOURCE.replace('cmd[-4]', 'cmd[n]').replace('cmd[-3]', 'cmd[n]').replace('cmd[-2]', 'cmd[n]')
    assert m.variants(loads, 'f') == []
    called = SOURCE.replace('| cmd[5];', '| g(cmd[5]);').replace('| cmd[-1];', '| g(cmd[-1]);')
    assert m.variants(called, 'f') == []
    assert m.variants(SOURCE, 'missing') == []
