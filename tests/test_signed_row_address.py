from decomprepair import registry
from decomprepair.signed_row_address import variants

HEADER = 'typedef signed char s8; typedef unsigned short u16; typedef unsigned int u32;'
FLAGS = '-G0 -mips3 -mgp32 -mfp32 -O1'
SOURCE = '''
void f(void) {
    s8 index;
    u16 (*row)[8];
    u16 *result;
    index = read_signed_byte();
    row = get_rows();
    result = row[index];
    use(result);
}
'''


def test_commutes_the_bounded_signed_offset():
    result = variants(SOURCE, 'f', HEADER, FLAGS)
    assert len(result) == 1
    assert 'result = (u16 *)((index * 16) + (u32)row);' in result[0][1]
    assert any(item.module.endswith('signed_row_address') for item in registry.declared())


def test_rejects_unsafe_types_and_shadowing():
    assert not variants(SOURCE, 'f', HEADER, '-mgp64')
    assert not variants(SOURCE, 'f', HEADER, FLAGS + ' -Dindex=x')
    assert not variants(SOURCE.replace('s8 index;', 's32 index;'), 'f', HEADER, FLAGS)
    assert not variants(SOURCE.replace('[8]', '[999999999]'), 'f', HEADER, FLAGS)
    assert not variants(SOURCE.replace('    result =', '    { int index; use(index); }\n    result ='), 'f', HEADER, FLAGS)
    assert not variants(SOURCE.replace('    result =', '    if (index)\n    result ='), 'f', HEADER, FLAGS)
    assert not variants(SOURCE.replace('    result =', '    { int other, index; use(index); }\n    result ='), 'f', HEADER, FLAGS)
    assert not variants(SOURCE.replace('    result =', '    { int u32; use(u32); }\n    result ='), 'f', HEADER, FLAGS)
