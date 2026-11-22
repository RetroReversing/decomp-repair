from decomprepair.measured_halfword_index import variants

SOURCE = '''s32 f(u16 *p) {
    s32 index;
    index = 0;
    while (*(((index & 0xff) * 2) + p) != 0xffff) index++;
    return index;
}'''
ROWS = [(' ', 'andi $v0, $a1, 0xff', 'andi $v0, $a1, 0xff'),
        ('i', 'sll $v0, $v0, 1', 'sll $v0, $v0, 2'),
        (' ', 'addu $v0, $v0, $a0', 'addu $v0, $v0, $a0'),
        (' ', 'lhu $v0, ($v0)', 'lhu $v0, ($v0)')]
ASM = 'addiu $sp, $sp, -8\njr $ra\naddiu $sp, $sp, 8'


def test_correct_halfword_index_and_combine_leaf_frame():
    result = dict(variants(SOURCE,'f','',ROWS,ASM))
    assert '*((index & 0xff) + p)' in result['halfword_index_scale']
    assert 'u8 __repair_frame[8];' in result['halfword_index_scale_with_frame']


def test_requires_matching_shift_mask_and_halfword_pointer():
    assert not variants(SOURCE,'f','',[],ASM)
    assert not variants(SOURCE.replace('u16 *p','u32 *p'),'f','',ROWS,ASM)
    assert not variants(SOURCE.replace('0xff','0xfe'),'f','',ROWS,ASM)
    assert not variants(SOURCE,'f','#define index get_index()',ROWS,ASM)
    assert not variants(SOURCE,'f','',ROWS[:1]+ROWS[2:],ASM)
