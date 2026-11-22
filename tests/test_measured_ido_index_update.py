from decomprepair.measured_ido_index_update import variants

SOURCE = '''void add(Menu *menu, int value) {
    register s32 index;
    if (value == -1) {
        index = menu->count;
        menu->rows[index].id = index;
    }
    menu->count += 1;
}
'''
T = ['lw $t7, 0x28($sp)', 'lw $t9, 0x78($t7)', 'sll $t6, $t9, 2', 'addu $t6, $t6, $t9',
     'sll $t6, $t6, 3', 'addu $t0, $t7, $t6', 'sw $t9, 0x8c($t0)',
     'lw $s0, 0x28($sp)', 'lw $t3, 0x78($s0)', 'addiu $t5, $t3, 1', 'sw $t5, 0x78($s0)']
C = ['lw $t7, 0x28($sp)', 'lw $s0, 0x78($t7)', 'lw $t9, 0x28($sp)', 'sll $t6, $s0, 2',
     'addu $t6, $t6, $s0', 'sll $t6, $t6, 3', 'addu $t0, $t9, $t6', 'sw $s0, 0x8c($t0)',
     'lw $t3, 0x28($sp)', 'lw $t5, 0x78($t3)', 'addiu $t8, $t5, 1', 'sw $t8, 0x78($t3)']
ROWS = [('r', T[i] if i < len(T) else '', C[i] if i < len(C) else '') for i in range(max(len(T), len(C)))]


def test_reuses_index_and_registers_owner():
    result = variants(SOURCE, 'add', '', ROWS)
    assert len(result) == 1
    assert 'menu->rows[menu->count].id = menu->count;' in result[0][1]
    assert 'register Menu *__repair_owner;' in result[0][1]
    assert '__repair_owner = menu;\n    __repair_owner->count += 1;' in result[0][1]


def test_requires_matching_evidence_and_unshared_temporary():
    assert not variants(SOURCE, 'add', '', [('r', t, t) for t in T])
    assert not variants(SOURCE.replace('menu->count += 1;', 'use(index); menu->count += 1;'), 'add', '', ROWS)
    assert not variants(SOURCE, 'add', 'volatile int count;', ROWS)
    assert not variants(SOURCE.replace('register s32', 'volatile s32'), 'add', '', ROWS)
