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
    wide = SOURCE.replace('    u8 index;', '    u32 index;')
    assert len(variants(wide, 'f', HEADER, FLAGS)) == 1


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

SLOT_SOURCE = '''
extern unsigned char input[];
extern char table[];
void f(int position) {
    __typeof__(*input + 0) index;
    s32 *row;
    index = *(input + position);
    { __typeof__(table + 0) base; do { base = table; } while (0); row = base + (index * 4); }
    use(row);
}
'''


def test_commutes_a_scoped_table_base_with_a_proven_byte_index():
    children = variants(SLOT_SOURCE, 'f', HEADER, FLAGS)
    assert len(children) == 2
    assert children[0][0] == 'commute_scoped_slot_address'
    assert children[1][0] == 'commute_weighted_slot_address'
    assert 'do { do { base = table; } while (0); } while (0);' in children[1][1]
    assert 'row = (s32 *)((index * 4) + (u32)base);' in children[1][1]
    assert 'row = (s32 *)((index * 4) + (u32)base);' in children[0][1]


def test_scoped_slot_rejects_unbounded_or_ambiguous_types():
    assert variants(SLOT_SOURCE.replace('    index = *(input + position);', '    index = *(input + position);\n    index = position;'), 'f', HEADER, FLAGS) == []
    assert variants(SLOT_SOURCE.replace('extern unsigned char input[];', '#if X\nextern unsigned char input[];\n#endif'), 'f', HEADER, FLAGS) == []
    assert variants(SLOT_SOURCE.replace('extern char table[];', '#if X\nextern char table[];\n#endif'), 'f', HEADER, FLAGS) == []
    assert variants(SLOT_SOURCE.replace('    index = *(input + position);', '    { __typeof__(row) input; use(input); }\n    index = *(input + position);'), 'f', HEADER, FLAGS) == []
    assert variants(SLOT_SOURCE.replace('void f(int position)', 'void f(int *input, int position)'), 'f', HEADER, FLAGS) == []
    assert variants(SLOT_SOURCE.replace('void f(int position)', 'void f(s32 *table, int position)'), 'f', HEADER, FLAGS) == []
    assert variants(SLOT_SOURCE.replace('    index = *(input + position);', '    s32 *table;\n    index = *(input + position);'), 'f', HEADER, FLAGS) == []
    assert variants(SLOT_SOURCE.replace('    index = *(input + position);', '    __typeof__(row) table;\n    index = *(input + position);'), 'f', HEADER, FLAGS) == []
    assert variants(SLOT_SOURCE.replace('void f(int position)', 'void f(int u32, int position)'), 'f', HEADER, FLAGS) == []
    assert variants(SLOT_SOURCE, 'f', HEADER, FLAGS + ['-mabi=64']) == []


def test_unrelated_header_volatile_does_not_hide_the_repair():
    assert len(variants(SLOT_SOURCE, 'f', HEADER + '\nextern volatile int status;', FLAGS)) == 2
    assert not variants(SLOT_SOURCE.replace('    s32 *row;', '    volatile s32 *row;'), 'f', HEADER, FLAGS)
