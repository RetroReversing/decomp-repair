"""m2c's goto loop with a shared skip block, as a do/while."""
from decomprepair import goto_loop_repairs as g

SOURCE = '''s32 f(void *arg0, s32 arg1) {
    s32 var_a0;
    u32 var_a2;
    void *var_v1;

    var_a2 = 4;
    var_a0 = 0x3A0;
    var_v1 = M2C_FIELD(arg0, s32 *, 0x6C) + 0x20;
loop_1:
    if (M2C_FIELD(var_v1, u8 *, 0x1FC) == 0) {
        var_a0 += 0xE8;
        goto block_8;
    }
    if (*(D + var_a0) != arg1) {
        var_a0 += 0xE8;
block_8:
        var_a2 += 1;
        var_v1 += 8;
        if (var_a2 >= 0x21U) {
            return 0;
        }
        goto loop_1;
    }
    return 1;
}
'''


def test_the_loop_it_came_from():
    # An N64 function at 75.7%: exact as this loop.
    (family, out), = g.variants(SOURCE, 'f')
    assert family == 'goto_loop'
    assert '''    do {
        if ((M2C_FIELD(var_v1, u8 *, 0x1FC) != 0) && (*(D + var_a0) == arg1)) {
            return 1;
        }
        var_a0 += 0xE8;
        var_a2 += 1;
        var_v1 += 8;
    } while (var_a2 < 0x21U);
    return 0;
}''' in out and 'goto' not in out


def test_left_alone_otherwise():
    assert g.variants(SOURCE.replace('        var_a0 += 0xE8;\nblock_8:', '        var_a0 += 0xE4;\nblock_8:'), 'f') == []
    assert g.variants(SOURCE.replace('    return 1;\n}', '    goto block_8;\n    return 1;\n}'), 'f') == []
