from decomprepair.draft_call_recovery import variants
from decomprepair.ido_indirect_event import applies, rewrite

DRAFT = '''
void emit(void *runner, s32 index) {
    s32 event;
    void *method;
    void *object;
    event = 41;
    object = *(M2C_FIELD(runner, s32 *, 0x44) + (index * 0x60));
    method = M2C_FIELD(object, void **, 0x28);
    M2C_FIELD(method, M2C_UNK (**)(void *, s32 *), 0x2C)(M2C_FIELD(method, s16 *, 0x28) + object, &event);
}
'''
ASSEMBLY = '\n'.join(
    f'/* {at * 4:04X} {0x80004000 + at * 4:08X} {word} */ {line}'
    for at, (word, line) in enumerate((
        ('27BDFFC8', 'addiu $sp, $sp, -0x38'),
        ('240E0029', 'addiu $t6, $zero, 41'),
        ('AFBF0014', 'sw $ra, 0x14($sp)'),
        ('AFAE002C', 'sw $t6, 0x2C($sp)'),
        ('8C8F0044', 'lw $t7, 0x44($a0)'),
        ('0005C080', 'sll $t8, $a1, 2'),
        ('0305C023', 'subu $t8, $t8, $a1'),
        ('0018C140', 'sll $t8, $t8, 5'),
        ('01F8C821', 'addu $t9, $t7, $t8'),
        ('8F230000', 'lw $v1, ($t9)'),
        ('27A5002C', 'addiu $a1, $sp, 44'),
        ('8C620028', 'lw $v0, 0x28($v1)'),
        ('8C59002C', 'lw $t9, 0x2C($v0)'),
        ('84480028', 'lh $t0, 0x28($v0)'),
        ('0320F809', 'jalr $t9'),
        ('01032021', 'addu $a0, $t0, $v1'),
        ('8FBF0014', 'lw $ra, 0x14($sp)'),
        ('27BD0038', 'addiu $sp, $sp, 0x38'),
        ('03E00008', 'jr $ra'),
        ('00000000', 'nop'),
    ))
)


def test_ido_draft_retains_the_callback_stack_word_and_receiver_adjustment():
    assert applies(ASSEMBLY)
    [(family, fixed)] = variants(DRAFT, 'emit', ASSEMBLY, '', 'ido-7.1')
    assert family == 'ido_indirect_event'
    assert 'int __m2c_event_value = 41;' in fixed
    assert 'int __m2c_event_before[2];' in fixed
    assert 'int __m2c_event_after[1];' in fixed
    assert '(short *)__m2c_event_adjustment' in fixed
    assert '&__m2c_event_value' in fixed
    assert not variants(DRAFT, 'emit', ASSEMBLY, '', 'gcc-2.7.2-kmc')


def test_ido_event_requires_a_matching_slot_constant_and_unowned_signature():
    assert not rewrite(DRAFT, 'emit', ASSEMBLY.replace('sw $t6, 0x2C($sp)', 'sw $t6, 0x30($sp)'))
    assert not rewrite(DRAFT.replace('event = 41', 'event = 42'), 'emit', ASSEMBLY)
    assert not rewrite(DRAFT, 'emit', ASSEMBLY, 'void emit(void *, int);')
