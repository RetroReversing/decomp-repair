from decomprepair import symbol_base_repairs as repair

SOURCE = '''
extern u8 flags;
void f(void) {
    prepare();
    flags |= 0x21;
    finish();
}
'''
ROWS = [
    'lui $v1, %hi(flags)',
    'addiu $v1, $v1, %lo(flags)',
    'lbu $v0, ($v1)',
    'ori $v0, $v0, 0x21',
    'sb $v0, ($v1)',
]


def asm(rows):
    return '\n'.join(f'/* {index*4:06X} {0x80000000+index*4:08X} 00000000 */ {op}'
                     for index, op in enumerate(rows))


def choices(source, rows=ROWS):
    return [text for family, text in repair.variants(source, 'f', asm(rows))
            if family == repair.BYTE_UPDATE_FAMILY]


def test_uses_one_local_address_for_a_single_byte_update():
    [child] = choices(SOURCE)
    assert 'u8 *__base_flags;' in child
    assert 'prepare();\n    __base_flags = &flags;\n    (*__base_flags) |= 0x21;' in child


def test_requires_matching_address_mask_and_value_register():
    assert not choices(SOURCE, ROWS[:-1] + ['sb $v0, ($at)'])
    assert not choices(SOURCE, ROWS[:-1] + ['sb $a0, ($v1)'])
    assert not choices(SOURCE.replace('0x21', '0x31'))


def test_preserves_unbraced_guard_and_nonbyte_symbol():
    assert not choices(SOURCE.replace('    flags |=', '    if (ready())\n        flags |='))
    assert not choices(SOURCE.replace('extern u8', 'extern u16'))
