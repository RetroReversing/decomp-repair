from decomprepair.last_byte_mask_repairs import FAMILY, residual, variants

ROWS = [
    (' ', 'lbu $v0, 0x40($a0)', 'lbu $v0, 0x40($a0)'),
    (' ', 'addiu $v1, $zero, 2', 'addiu $v1, $zero, 2'),
    ('i', 'andi $v0, $v0, 0xff', 'andi $v0, $v0, 0x7f'),
    (' ', 'bne $v0, $v1, 0x24', 'bne $v0, $v1, 0x24'),
]
SOURCE = """int f(int i) {
    if ((*(u8 *)((u8 *)&flags + (i * 16)) & 0x7f) == 2) {
        return 1;
    }
    return 0;
}
"""


def test_full_byte_mask_uses_linked_load_and_comparison():
    assert residual(ROWS) == tuple(ROWS)
    proposals = variants(SOURCE, 'f', ROWS)
    assert len(proposals) == 5
    assert all(family == FAMILY and '& 0x7f' not in text for family, text in proposals)
    assert all(text.count('&flags') == 1 for _, text in proposals)


def test_reject_wrong_register_wrong_source_or_second_difference():
    assert not residual(ROWS[:-1] + [(' ', 'bne $a0, $v1, 0x24', 'bne $a0, $v1, 0x24')])
    assert not residual(ROWS + [('i', 'nop', 'move $v0, $a0')])
    assert not variants(SOURCE.replace('== 2', '== 3'), 'f', ROWS)
    assert not variants(SOURCE.replace('return 0;', SOURCE.split('{', 1)[1][:-2]), 'f', ROWS)
