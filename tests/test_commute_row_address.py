from decomprepair import registry
from decomprepair.commute_row_address import variants

HEADER = 'typedef unsigned char u8; typedef unsigned int u32; typedef signed int s32;'
FLAGS = ['-G0', '-mips3', '-mgp32', '-mfp32', '-O1']
SOURCE = '''
void f(void) {
    u8 index;
    s32 offset;
    u8 *base;
    u8 *row;
    offset = index * 0x110;
    row = base + offset;
    use(row);
}
'''


def test_commutes_bounded_offset_using_32_bit_mips_address():
    children = variants(SOURCE, 'f', HEADER, FLAGS)
    assert len(children) == 1
    assert 'row = (u8 *)(offset + (u32)base);' in children[0][1]
    assert any(entry.module.endswith('commute_row_address') for entry in registry.declared())


def test_declines_unknown_width_overflow_shadow_and_preprocessing():
    assert variants(SOURCE, 'f', HEADER, ['-mgp64']) == []
    assert variants(SOURCE, 'f', HEADER, FLAGS + ['-mabi=64']) == []
    assert variants(SOURCE, 'f', HEADER, FLAGS + ['-mabi', '64']) == []
    assert variants(SOURCE.replace('0x110', '010'), 'f', HEADER, FLAGS) == []
    assert variants(SOURCE, 'f', HEADER, FLAGS + ['-DX=1']) == []
    assert variants(SOURCE.replace('0x110', '0x1000000'), 'f', HEADER, FLAGS) == []
    assert variants(SOURCE.replace('u8 index;', 's32 index;'), 'f', HEADER, FLAGS) == []
    assert variants(SOURCE.replace('    row =', '    if (index)\n    row ='), 'f', HEADER, FLAGS) == []
    assert variants(SOURCE.replace('    u8 *base;', '    u8 *base;\n    { int *base; use(base); }'), 'f', HEADER, FLAGS) == []
    assert variants(SOURCE, 'f', HEADER + '\n#include "x.h"', FLAGS) == []
    assert variants(SOURCE.replace('    u8 *row;', '    u8 *row;\n    { typedef int u32; }'), 'f', HEADER, FLAGS) == []
    for shadow in ('u8', 'u32'):
        assert variants(SOURCE.replace('    u8 *row;', f'    u8 *row;\n    int {shadow};'), 'f', HEADER, FLAGS) == []
        assert variants(SOURCE.replace('    u8 *row;', f'    u8 *row;\n    __typeof__(index) {shadow};'), 'f', HEADER, FLAGS) == []
