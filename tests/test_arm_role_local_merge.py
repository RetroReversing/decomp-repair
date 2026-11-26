"""Two locals holding the same value in different switch arms written as one variable."""
from decomprepair import arm_role_local_merge as m

SOURCE = '''void f(u8 *cmd, u32 *out)
{
    s32 r;
    s32 r_b1;
    s32 k;
    s32 b;
    for (;;) {
        switch (*cmd) {
        case 4:
            b = cmd[1];
            r = b & 0x1F;
            out[0] = r << 9;
            break;
        case 5:
            b = cmd[2];
            r_b1 = b & 0x1F;
            k = b + 1;
            out[1] = r_b1 | k;
            break;
        default:
            return;
        }
    }
}
'''


def test_same_value_in_two_arms_is_one_variable():
    # An SN GCC 2.8.1 model loader's triangle arms: 410 -> 365 with the low index one variable in both arms.
    (family, text), = m.variants(SOURCE, 'f')
    assert family == 'arm_role_local_merge'
    assert 's32 r_b1;' not in text and 'r = b & 0x1F;\n            k = b + 1;\n            out[1] = r | k;' in text
    assert '    s32 r;\n    s32 k;\n' in text


def test_left_alone_otherwise():
    # different values, a fall-through arm, a use outside the switch, read before set in an arm
    assert m.variants(SOURCE.replace('r_b1 = b & 0x1F;', 'r_b1 = b & 0x3F;'), 'f') == []
    assert m.variants(SOURCE.replace('out[0] = r << 9;\n            break;', 'out[0] = r << 9;'), 'f') == []
    assert m.variants(SOURCE.replace('return;', 'out[2] = r_b1; return;'), 'f') == []
    assert m.variants(SOURCE.replace('b = cmd[2];\n            r_b1', 'b = r_b1;\n            r_b1'), 'f') == []
