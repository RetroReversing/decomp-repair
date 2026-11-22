from decomprepair.measured_global_offset_reuse import variants

SOURCE = '''
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern M2C_UNK global;
void f(void) {
    void *head;
    void *tail;
    head = (char *)&global + 0x100;
    tail = M2C_FIELD(head, void **, 4);
    if (tail == NULL) {
        M2C_FIELD(head, void **, 4) = NULL;
    }
}
'''
ROWS = [
    ('r', 'lui $v0, %hi(G)', 'lui $s2, %hi(G)'),
    ('r', 'addiu $v0, $v0, %lo(G)', 'addiu $s2, $s2, %lo(G)'),
    ('r', 'lw $s0, ($v0)', 'lw $s0, ($s2)'),
    ('r', 'move $s2, $v0', 'move $s3, $s2'),
]
ASM = 'addiu $sp, $sp, -0x28\nsw $s0, 0x18($sp)\njal cleanup\nnop\n'


def test_fold_global_offset_and_offer_frame_repair():
    candidates = dict(variants(SOURCE, 'f', '', ROWS, ASM))
    assert set(candidates) == {'measured_global_offset_reuse', 'global_offset_with_frame'}
    assert 'head = (char *)&global' not in candidates['measured_global_offset_reuse']
    assert candidates['measured_global_offset_reuse'].count('M2C_FIELD(&global, void **, 0x104)') == 2
    assert 'volatile u64 scratch;' in candidates['global_offset_with_frame']


def test_decline_unsafe_offsets_and_shadowing():
    for source, header, rows in [
        (SOURCE, '', []),
        (SOURCE.replace('void *head;', 'static void *head;'), '', ROWS),
        (SOURCE.replace('tail = M2C_FIELD', 'use(&head); tail = M2C_FIELD'), '', ROWS),
        (SOURCE.replace('if (tail == NULL) {', 'if (tail == NULL) {\n        int global;'), '', ROWS),
        (SOURCE, '#define head other()', ROWS),
        (SOURCE, '#undef M2C_FIELD', ROWS),
        (SOURCE.replace('(*(type_ptr)', '(effect(), *(type_ptr)'), '', ROWS),
    ]:
        assert variants(source, 'f', header, rows, ASM) == []
