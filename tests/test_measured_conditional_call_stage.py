from decomprepair.measured_conditional_call_stage import variants

SOURCE = '''s32 setup(s32 arg) {
    M2C_UNK choice;
    M2C_FIELD(display, s8 *, 0x245) = 1;
    M2C_FIELD(M2C_FIELD(&base, void **, 0x20), u16 *, 0x22) = 0U;
    if (M2C_FIELD(M2C_FIELD(&base, void **, 0x28), s16 *, 2) == 2) {
        choice = 0x17;
    } else {
        reset(0);
        enable(0x16);
        choice = 0xe;
    }
    copy(arg, choice);
    return 0;
}
'''
T = ['lui $v0, %hi(slot)', 'lw $v0, %lo(slot)($v0)', 'lui $v1, %hi(cond)', 'lw $v1, %lo(cond)($v1)',
     'sh $zero, 0x22($v0)', 'lh $v1, 2($v1)', 'move $a0, $s0', 'addiu $a1, $zero, 0xe', 'jal copy', 'nop']
C = ['lui $v0, %hi(slot)', 'lw $v0, %lo(slot)($v0)', 'sh $zero, 0x22($v0)', 'lui $v0, %hi(cond)',
     'lw $v0, %lo(cond)($v0)', 'lh $v1, 2($v0)', 'addiu $a1, $zero, 0xe', 'jal copy', 'move $a0, $s0']
ROWS = [('r', T[i] if i < len(T) else '', C[i] if i < len(C) else '') for i in range(max(len(T), len(C)))]


def resolve(name):
    return {'base': 0x1000, 'slot': 0x1020, 'cond': 0x1028}.get(name)


def test_stages_condition_and_call_owner():
    result = variants(SOURCE, 'setup', '', ROWS, resolve=resolve)
    assert len(result) == 1
    assert '__repair_condition_owner = M2C_FIELD(&base, void **, 0x28);' in result[0][1]
    assert result[0][1].count('__repair_call_owner = arg;') == 2
    assert 'copy(__repair_call_owner, choice);' in result[0][1]


def test_requires_relocation_evidence_and_nonvolatile_source():
    assert not variants(SOURCE, 'setup', '', ROWS)
    assert not variants(SOURCE, 'setup', '', ROWS, resolve=lambda _: 0)
    assert not variants(SOURCE.replace('s32 arg', 'volatile s32 arg'), 'setup', '', ROWS, resolve=resolve)
    assert not variants(SOURCE, 'setup', '', [('r', a, a) for a in T], resolve=resolve)
