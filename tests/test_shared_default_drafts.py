from decomprepair.shared_default_drafts import applies, rewrite

ASM = '''
glabel f
addiu $sp, $sp, -24
addiu $a1, $a1, -1
sltiu $v0, $a1, 3
beqz $v0, .Lfallback
sw $ra, 16($sp)
sll $v0, $a1, 2
lui $at, %hi(cases)
addu $at, $at, $v0
lw $v0, %lo(cases)($at)
jr $v0
nop
.Lfallback:
jal outside
nop
j .Lexit
nop
.Lsecond:
jal inside
nop
.Lexit:
lw $ra, 16($sp)
jr $ra
addiu $sp, $sp, 24
'''

DATA = '''
.section .rodata
dlabel cases
.word .Lfallback
.word .Lsecond
.word .Lfallback
.word 0
'''

SOURCE = '''
M2C_UNK inside(u32); /* extern */
M2C_UNK outside(u32); /* extern */

void f(s32 arg1) {
    u32 index;
    index = arg1 - 1;
    if (index < 3U) {
        switch (arg1) {
        case 2:
            inside(index);
            return;
        }
    } else {
    case 1:
    case 3:
        outside(index);
    }
}
'''


def test_shared_cases_rejoin_default_and_keep_the_selector_in_its_original_abi_slot():
    assert applies(ASM)
    candidate = rewrite(SOURCE,'f',ASM,DATA)
    assert 'void f(s32 arg0, s32 arg1)' in candidate
    assert 'default:\n    case 1:\n    case 3:\n        outside();\n        break;' in candidate
    assert 'case 2:\n        inside();\n        break;' in candidate
    assert 'M2C_UNK inside();' in candidate


def test_requires_the_table_direct_call_blocks_and_untyped_draft_owned_callees():
    assert not rewrite(SOURCE,'f',ASM,'')
    assert not rewrite(SOURCE,'f',ASM,DATA.replace('.Lsecond','.Lfallback'))
    assert not rewrite(SOURCE,'f',ASM.replace('jal inside\nnop','jal inside\nmove $a0, $a1'),DATA)
    assert not rewrite(SOURCE,'f',ASM,DATA,'void inside(int);')
    assert not rewrite(SOURCE.replace('case 3:', 'case 4:'),'f',ASM,DATA)
    assert not rewrite(SOURCE.replace('inside(index);', 'inside(arg1);'),'f',ASM,DATA)
