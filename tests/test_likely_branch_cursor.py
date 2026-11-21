import pytest

from decomprepair import likely_branch_cursor as repair

ASM = '''
.Lloop:
    lbu $v0, 0($s2)
    lw $s3, 0x0($s4)
    beql $v0, $zero, .Ljoin
    addu $s4, $s3, $zero
    jal detach
    nop
    jal unlock
    addu $s4, $s3, $zero
.Ljoin:
    bnez $s4, .Lloop
    nop
'''

DRAFT = '''
void run(void) {
    void *var_s4;
    void *temp_s3;
    var_s4 = list;
    if (var_s4 != NULL) {
        do {
            temp_s3 = M2C_FIELD(var_s4, void **, 0);
            if (active == 0) {
                var_s4 = temp_s3;
            } else {
                detach(var_s4);
                var_s4 = temp_s3;
                unlock();
            }
        } while (var_s4 != NULL);
    }
}
'''


def test_split_keeps_cursor_move_on_taken_path_only():
    assert repair.applies(ASM)
    expanded = repair.draft_asm(ASM)
    assert '''bnez $v0, .Ldecomp_cursor_active
    nop
    addu $s4, $s3, $zero
    b .Ljoin
    nop
.Ldecomp_cursor_active:
    jal detach''' in expanded
    assert expanded.count('addu $s4, $s3, $zero') == 2
    assert 'jal unlock\n    addu $s4, $s3, $zero\n.Ljoin:' in expanded


def test_shared_advance_preserves_body_and_call_order():
    assert repair.rewrite(DRAFT, 'run', ASM) == DRAFT.replace(
        '''if (active == 0) {
                var_s4 = temp_s3;
            } else {''', 'if (active != 0) {'
    ).replace(
        '''                var_s4 = temp_s3;
                unlock();
            }''', '''                unlock();
            }
            var_s4 = temp_s3;'''
    )


@pytest.mark.parametrize('asm', [
    ASM.replace('jal unlock\n    addu $s4, $s3, $zero', 'jal unlock\n    nop'),
    ASM.replace('bnez $s4, .Lloop', 'bnez $s2, .Lloop'),
    ASM.replace('lw $s3, 0x0($s4)', 'lw $s3, 0x4($s4)'),
])
def test_requires_both_advances_and_the_same_backedge(asm):
    assert repair.draft_asm(asm) == asm
    assert repair.rewrite(DRAFT, 'run', asm) is None


@pytest.mark.parametrize('draft', [
    DRAFT.replace('unlock();', 'unlock(var_s4);'),
    DRAFT.replace('detach(var_s4);', 'detach(&(var_s4));'),
    DRAFT.replace('detach(var_s4);', 'void *var_s4 = 0;\n                detach(var_s4);'),
])
def test_keeps_observable_local_advances_intact(draft):
    assert repair.rewrite(draft, 'run', ASM) is None
