from decomprepair import mips_return_paths as r


def asm(*rows):
    return 'glabel f\n' + '\n'.join(f'/* {i * 4:X} {0x80000000 + i * 4:08X} 00000000 */  {row}' for i, row in enumerate(rows)) + '\n'


def test_a_value_written_for_nothing_but_the_return():
    assert r.contract(asm('addiu $v0, $a0, 0x1', 'jr $ra', 'nop')) == 'value'
    assert r.contract(asm('jr $ra', 'addiu $v0, $zero, 0x3')) == 'value'


def test_no_write_is_void():
    assert r.contract(asm('sw $zero, 0x0($a0)', 'jr $ra', 'nop')) == 'void'


def test_a_tested_copy_or_a_callee_result_is_only_a_hint():
    # the tail of a function that returns `v` (or tests `v` and returns nothing): `v = a2; if (!v) v = g();`
    text = asm('addiu $sp, $sp, -0x18', 'sw $ra, 0x10($sp)', 'addu $v0, $a2, $zero', 'bnez $v0, .L80000018', 'nop',
               'jal g', 'nop', 'lw $ra, 0x10($sp)', 'jr $ra', 'addiu $sp, $sp, 0x18')
    text = text.replace('/* 1C 8000001C', '.L80000018:\n/* 1C 8000001C')
    assert r.contract(text) == 'tested'


def test_a_scratch_read_on_the_way_out_or_the_entry_value_says_nothing():
    assert r.contract(asm('lw $v0, 0x0($a0)', 'sw $v0, 0x4($a0)', 'jr $ra', 'nop')) is None
    assert r.contract(asm('beqz $a0, .L8000000C', 'nop', 'addiu $v0, $zero, 1', 'jr $ra', 'nop')
                      .replace('/* C 8000000C', '.L8000000C:\n/* C 8000000C')) is None
