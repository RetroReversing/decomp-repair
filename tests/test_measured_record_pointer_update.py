from decomprepair.measured_record_pointer_update import variants

SOURCE = '''extern void *ctx;
typedef struct { short field_0; char pad[6]; void *field_8; int field_C; } __repair_record_ctx;
void update(void *arg) {
    s32 state;
    void *previous;
    state = lock();
    previous = ((__repair_record_ctx*)ctx)->field_8;
    ((__repair_record_ctx*)ctx)->field_8 = arg;
    ((__repair_record_ctx*)ctx)->field_C = (s32) M2C_FIELD(previous, s32 *, 4);
    ((__repair_record_ctx*)ctx)->field_0 = 1;
    unlock(state, previous);
}
'''
T = ['lui $a0, %hi(ctx)', 'lw $a0, %lo(ctx)($a0)', 'sw $s0, 8($a0)', 'lw $a1, 8($a0)',
     'addiu $v1, $zero, 1', 'sh $v1, ($a0)', 'lw $v1, 4($a1)', 'sw $v1, 0xc($a0)',
     'jal unlock', 'move $a0, $v0']
C = ['lui $a0, %hi(ctx)', 'lw $a0, %lo(ctx)($a0)', 'lw $a1, 8($a0)', 'sw $s0, 8($a0)',
     'lw $a2, 4($a1)', 'addiu $v1, $zero, 1', 'sh $v1, ($a0)', 'sw $a2, 0xc($a0)']
ROWS = [('r', T[i] if i < len(T) else '', C[i] if i < len(C) else '') for i in range(len(T))]


def test_reads_new_pointer_after_storing_and_setting_flag():
    result = variants(SOURCE, 'update', '', ROWS)
    assert len(result) == 1
    fixed = result[0][1]
    assert fixed.index('field_8 = arg') < fixed.index('field_0 = 1') < fixed.index('previous = ')
    assert fixed.index('previous = ') < fixed.index('field_C = ')


def test_requires_matching_memory_order_and_nonvolatile_source():
    assert not variants(SOURCE, 'update', '', [('r', x, x) for x in T])
    assert not variants(SOURCE.replace('field_C =', 'field_10 ='), 'update', '', ROWS)
    assert not variants(SOURCE.replace('extern void *ctx;', 'extern volatile void *ctx;'), 'update', '', ROWS)
    assert not variants(SOURCE.replace('previous = ((', '/* retain */ previous = (('), 'update', '', ROWS)
