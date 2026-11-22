from decomprepair.measured_kmc_list_append import variants

SOURCE = '''
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
s32 f(void *obj, s32 mode, s32 value) {
    s32 index;
    if (mode == 2) {
        M2C_FIELD(obj, s32 *, 0x14) = (s32) (index + 1);
        index = M2C_FIELD(obj, s32 *, 0x14);
        *(s32 *)((index * 4) + M2C_FIELD(obj, s32 *, 0x1C)) = value;
    }
    return 0;
}'''
TARGET = ['lw $a3, 0x1c($a0)', 'addiu $v0, $zero, 2', 'bne $a1, $v0, 0x28', 'nop',
          'lw $v0, 0x14($a0)', 'addiu $v1, $v0, 1', 'sll $v0, $v0, 2',
          'addu $v0, $v0, $a3', 'sw $v1, 0x14($a0)', 'sw $a2, 0($v0)',
          'jr $ra', 'move $v0, $zero']
ROWS = [('r', line, '') for line in TARGET]


def test_recover_uninitialized_index_from_measured_append():
    result = variants(SOURCE,'f','',ROWS)
    assert len(result)==1
    fixed = result[0][1]
    assert 's32 repair_list = M2C_FIELD(obj, s32 *, 0x1C);' in fixed
    assert fixed.index('index = M2C_FIELD(obj, s32 *, 0x14);') < fixed.index('= (s32) (index + 1)')
    assert '(index * 4) + repair_list' in fixed


def test_requires_target_offsets_uninitialized_local_and_plain_macro():
    assert not variants(SOURCE,'f','',[])
    assert not variants(SOURCE.replace('s32 index;', 's32 index = 0;'),'f','',ROWS)
    assert not variants(SOURCE.replace('0x1C','0x14'),'f','',ROWS)
    assert not variants(SOURCE.replace('(type_ptr)((s8 *)(expr) + (offset))','side_effect()'),'f','',ROWS)
    assert not variants(SOURCE,'f','#define index other',ROWS)
    assert not variants(SOURCE,'f','',ROWS[:-1])
