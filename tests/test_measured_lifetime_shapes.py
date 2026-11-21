from decomprepair import measured_lifetime_shapes as repairs

KMC = 'gcc-2.7.2-kmc'


def measured(source, target, changes, compiler=KMC, header=''):
    rows = [('r', op, changes[i]) if i in changes else (' ', op, op) for i, op in enumerate(target)]
    return repairs.variants(source + '\n', 'f', header, compiler, rows)


def test_guard_bypasses_the_result_copy():
    source = '''int f(void) {
    int result;
    if (ready) {
        result = read();
    }
    return result;
}'''
    target = ['beqz $v0, 0x14', 'nop', 'jal read', 'nop',
              'move $v0, $s1', 'lw $ra, 0x1c($sp)', 'jr $ra', 'nop']
    changes = {0: 'beqz $v0, 0x10'}
    [(family, fixed)] = measured(source, target, changes)
    assert family == 'guarded_local_return'
    assert '        result = read();\n        return result;\n    }' in fixed
    assert not measured(source.replace('int result;', 'int result = 0;'), target, changes)
    assert not measured(source.replace('    return result;', '    notify();\n    return result;'), target, changes)
    assert not measured(source, [*target[:4], 'move $v0, $zero', *target[5:]], changes)


def test_reset_can_move_past_the_allocation_that_does_not_read_it():
    source = '''void f(int pool) {
    int index;
    int count;
    int slot;
    index = 0;
    count = count16 & 0xffff;
    slot = alloc(pool, count * 8);
    consume(slot, index);
}'''
    target = ['move $a0, $s0', 'move $s2, $zero', 'andi $s0, $s1, 0xffff',
              'jal alloc', 'sll $a1, $s0, 3']
    swap = {0: target[1], 1: target[0]}
    [(family, fixed)] = measured(source, target, swap)
    assert family == 'post_call_index_reset'
    assert 'slot = alloc(pool, count * 8);\n    index = 0;\n    consume' in fixed
    assert not measured(source.replace('count * 8', 'index * 8'), target, swap)
    assert not measured(source.replace('    index = 0;', '    if (ready)\n        index = 0;'), target, swap)
    assert not measured(source, [*target[:2], 'beqz $s0, 4', *target[3:]], swap)


def test_use_a_single_float_local_for_the_load_and_both_branch_results():
    source = '''void f(float *value) {
    float result;
    double initial;

    initial = (double) *value;
    if (initial < cutoff) {
        result = (float) (initial + step);
    } else {
        result = 1.0f;
    }
    *value = result;
}'''
    target = ['cvt.s.d $f2, $f0', 'lui $at, 0x3f80', 'mtc1 $at, $f2', 'swc1 $f2, ($a1)']
    changes = {0: 'cvt.s.d $f0, $f0', 2: 'mtc1 $at, $f0', 3: 'swc1 $f0, ($a1)'}
    [(family, fixed)] = measured(source, target, changes)
    assert family == 'float_branch_carrier'
    assert 'initial' not in fixed
    assert 'result = (double) *value;' in fixed
    assert 'result = (float) (result + step);' in fixed
    assert not measured(source.replace('float *value', 'double *value'), target, changes)
    assert not measured(source.replace('initial + step', 'initial * step'), target, changes)
    assert not measured(source, target, changes | {3: 'swc1 $f0, 4($a1)'})


def test_drop_the_redundant_argument_from_an_ido_wrapper():
    source = '''int work(int, int, int); /* extern */
void f(int object, int mode) {
    work(mode, object + 136, object);
}'''
    target = ['addiu $sp, $sp, -0x18', 'move $a3, $a0', 'sw $ra, 0x14($sp)',
              'move $a0, $a1', 'jal work', 'addiu $a1, $a3, 0x88', 'jr $ra', 'nop']
    changes = {1: 'move $a2, $a0', 5: 'addiu $a1, $a2, 0x88'}
    [(family, fixed)] = measured(source, target, changes, 'ido-7.1')
    assert family == 'drop_duplicate_call_argument'
    assert 'work(int, int);' in fixed
    assert 'work(mode, object + 136);' in fixed
    assert not measured(source, target, changes)
    assert not measured(source, target, changes, 'ido-7.1', 'int work(int, int, int);')
    assert not measured(source.replace('+ 136', '+ 132'), target, changes, 'ido-7.1')
    assert not measured(source.replace(', object);', ', mode);'), target, changes, 'ido-7.1')


def test_ido_counter_update_binds_only_the_two_counter_accesses():
    target = (
        'addiu $sp, $sp, -8', 'move $a3, $a0', 'lw $a2, 0x40($a3)',
        'addiu $t6, $a2, 1', 'sw $t6, 0x40($a3)', 'sll $t7, $a2, 2',
        'addu $t8, $a0, $t7', 'sw $a1, 0x10($t8)', 'b .L28',
        'nop', 'addiu $sp, $sp, 8', 'jr $ra', 'nop',
    )
    rows = [(' ', op, op) for op in target]
    rows[1] = ('<', target[1], '')
    rows[2] = ('r', target[2], 'lw $a2, 0x40($a0)')
    rows[4] = ('r', target[4], 'sw $t6, 0x40($a0)')
    rows[8] = ('i', target[8], 'b .L24')
    source = '''
void insert(EntryList *list, Entry *item) {
    register s32 index;
    index = list->count;
    list->count = index + 1;
    list->items[index] = item;
}
'''
    [(family, fixed)] = repairs.variants(source, 'insert', '', 'ido-7.1', rows)
    assert family == 'ido_split_counter_update_base'
    assert 'register EntryList *__repair_counter_base = list;' in fixed
    assert fixed.count('__repair_counter_base->count') == 2
    assert 'list->items[index] = item;' in fixed
    assert not repairs.variants(source.replace('index + 1', 'index + 2'), 'insert', '', 'ido-7.1', rows)
    assert not repairs.variants(source, 'insert', '', 'gcc-2.7.2-kmc', rows)
